"""
Capture from Claude Desktop

Monitors Claude Desktop's session files and automatically commits turns.
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import hashlib

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from ..core.session_manager import SessionManager
from ..models.session import StateBlock, FileOperation


class ClaudeDesktopMonitor:
    """Monitor Claude Desktop sessions"""

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self.active_sessions = {}  # claude_session_id -> sessiongit_session
        self.last_activity = {}  # claude_session_id -> timestamp
        self.idle_threshold = timedelta(minutes=5)

        # Find Claude Desktop data directory
        self.claude_data_dir = self._find_claude_data_dir()

    def _find_claude_data_dir(self) -> Optional[Path]:
        """Find Claude Desktop data directory"""
        # Try common locations
        possible_paths = [
            Path.home() / "AppData" / "Local" / "Claude-3p" / "local-agent-mode-sessions",  # Windows
            Path.home() / "Library" / "Application Support" / "Claude",  # macOS
            Path.home() / ".config" / "Claude",  # Linux
        ]

        for path in possible_paths:
            if path.exists():
                return path

        return None

    def start(self):
        """Start monitoring Claude Desktop"""
        if not self.claude_data_dir:
            print("[WARNING] Claude Desktop data directory not found")
            return

        print(f"[OK] Monitoring Claude Desktop at: {self.claude_data_dir}")

        # Watch for file changes
        event_handler = ClaudeFileHandler(self)
        observer = Observer()
        observer.schedule(event_handler, str(self.claude_data_dir), recursive=True)
        observer.start()

        try:
            while True:
                time.sleep(1)
                self._check_idle_sessions()
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    def _check_idle_sessions(self):
        """Check for idle sessions and auto-save them"""
        now = datetime.now()

        for claude_id, last_time in list(self.last_activity.items()):
            if now - last_time > self.idle_threshold:
                # Session is idle - finalize it
                if claude_id in self.active_sessions:
                    session = self.active_sessions[claude_id]
                    self.session_manager.archive_session(session.metadata.session_id)
                    print(f"[OK] Auto-saved session: {session.metadata.title}")
                    del self.active_sessions[claude_id]
                    del self.last_activity[claude_id]

    def on_conversation_update(self, claude_session_file: Path):
        """Handle Claude conversation file update"""
        try:
            with open(claude_session_file) as f:
                data = json.load(f)

            claude_id = claude_session_file.stem

            # Extract conversation
            messages = self._extract_messages(data)

            if not messages:
                return

            # Get or create SessionGit session
            if claude_id not in self.active_sessions:
                session = self._create_session_from_claude(claude_id, data)
                self.active_sessions[claude_id] = session
            else:
                session = self.active_sessions[claude_id]

            # Process new messages
            self._process_messages(session, messages)

            # Update last activity
            self.last_activity[claude_id] = datetime.now()

        except Exception as e:
            print(f"Error processing Claude session: {e}")

    def _extract_messages(self, data: dict) -> list:
        """Extract messages from Claude session data"""
        # Claude Desktop stores messages in different formats
        # This is simplified - real implementation needs to handle
        # various Claude Desktop session file formats

        messages = []

        # Example structure (adjust based on actual Claude format)
        if 'messages' in data:
            messages = data['messages']
        elif 'conversation' in data:
            messages = data['conversation']

        return messages

    def _create_session_from_claude(self, claude_id: str, data: dict) -> 'Session':
        """Create SessionGit session from Claude session"""

        # Extract title (first user message or generated)
        title = "Claude Session"
        messages = self._extract_messages(data)
        if messages:
            first_user_msg = next(
                (m for m in messages if m.get('role') == 'user'),
                None
            )
            if first_user_msg:
                content = first_user_msg.get('content', '')
                title = content[:50] + "..." if len(content) > 50 else content

        session = self.session_manager.create_session(
            title=title,
            provider="anthropic",
            model=data.get('model', 'claude-sonnet-4-5'),
            source="claude-desktop",
        )

        return session

    def _extract_content(self, message: dict) -> str:
        """
        Extract content from message, handling both string and block list formats

        Claude API can return content as:
        - String: "Hello world"
        - List of blocks: [{"type": "text", "text": "Hello"}, {"type": "tool_use", ...}]
        """
        content = message.get('content', '')

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            # Content is a list of blocks - extract text blocks
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                    elif 'text' in block:
                        text_parts.append(block['text'])
                elif isinstance(block, str):
                    text_parts.append(block)
            return '\n'.join(text_parts)

        # Fallback: convert to string
        return str(content)

    def _process_messages(self, session: 'Session', messages: list):
        """Process messages and commit new turns"""

        # Find where we left off
        last_turn = session.metadata.total_turns

        # Process pairs of user/assistant messages
        # Skip over tool messages between them
        i = last_turn * 2  # Each turn = user + assistant message

        while i < len(messages):
            # Find next user message
            while i < len(messages) and messages[i].get('role') != 'user':
                i += 1

            if i >= len(messages):
                break

            user_msg = messages[i]
            i += 1

            # Find next assistant message (skip tool messages)
            while i < len(messages) and messages[i].get('role') not in ['assistant', 'user']:
                i += 1

            if i >= len(messages):
                break

            # If we hit another user message, there's no assistant response yet
            if messages[i].get('role') == 'user':
                continue

            assistant_msg = messages[i]
            i += 1

            # Extract file operations if available
            file_ops = self._extract_file_operations(assistant_msg)

            # Extract or generate state
            state = self._extract_state(assistant_msg, user_msg)

            # Commit turn
            self.session_manager.commit_turn(
                session=session,
                user_message=self._extract_content(user_msg),
                assistant_message=self._extract_content(assistant_msg),
                model=assistant_msg.get('model', 'claude-sonnet-4-5'),
                provider='anthropic',
                file_operations=file_ops,
                state=state,
            )

    def _extract_file_operations(self, message: dict) -> list[FileOperation]:
        """Extract file operations from assistant message"""
        operations = []

        # Check if message has tool_use
        if 'tool_uses' in message or 'tool_calls' in message:
            tool_uses = message.get('tool_uses') or message.get('tool_calls', [])

            for tool in tool_uses:
                tool_name = tool.get('name', '')

                # Map Claude tools to file operations
                if tool_name in ['read_file', 'Read']:
                    operations.append(FileOperation(
                        type='file_read',
                        path=tool.get('parameters', {}).get('file_path', ''),
                        timestamp=datetime.now(),
                    ))
                elif tool_name in ['write_file', 'Write']:
                    operations.append(FileOperation(
                        type='file_write',
                        path=tool.get('parameters', {}).get('file_path', ''),
                        timestamp=datetime.now(),
                    ))
                elif tool_name in ['edit_file', 'Edit']:
                    operations.append(FileOperation(
                        type='file_write',
                        path=tool.get('parameters', {}).get('file_path', ''),
                        timestamp=datetime.now(),
                    ))

        return operations

    def _extract_state(self, assistant_msg: dict, user_msg: dict) -> StateBlock:
        """
        Extract or generate state block

        In a full implementation, this would use an AI model to extract
        decisions, goals, and next steps from the conversation.
        For MVP, we create a basic state.
        """

        # Simple extraction - just use message content as context
        user_content = self._extract_content(user_msg)
        assistant_content = self._extract_content(assistant_msg)

        # Generate simple summary
        summary = f"User asked: {user_content[:100]}..."

        return StateBlock(
            goal=user_content[:200] if user_content else "Conversation",
            next_step="Continue conversation",
            context_summary=summary,
        )


class ClaudeFileHandler(FileSystemEventHandler):
    """Handle file system events from Claude Desktop"""

    def __init__(self, monitor: ClaudeDesktopMonitor):
        self.monitor = monitor

    def on_modified(self, event):
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Check if it's a conversation file
        if file_path.suffix == '.json' and 'session' in file_path.name.lower():
            self.monitor.on_conversation_update(file_path)
