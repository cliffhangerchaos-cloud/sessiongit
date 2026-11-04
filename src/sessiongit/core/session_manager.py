"""
Session Manager - Create, commit, and manage sessions
"""

import json
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import subprocess

from ..models.session import (
    Session,
    SessionMetadata,
    Turn,
    UserInput,
    AssistantOutput,
    StateBlock,
    FileOperation,
    GitRepo,
)
from .objects import ObjectStore
from .diff import FileTracker
from .secrets import get_redactor
from .config import get_config


class SessionManager:
    """Manage sessions and turns"""

    def __init__(self, storage_path: Path, enable_redaction: Optional[bool] = None):
        self.storage_path = Path(storage_path)
        # Don't create here - let caller decide when to create
        # This prevents accidental directory creation on read-only operations

        self.sessions_dir = self.storage_path / "sessions"

        self.object_store = ObjectStore(self.storage_path)

        # Read from config
        config = get_config()

        # Read redaction setting if not explicitly set
        if enable_redaction is None:
            enable_redaction = config.get('enable_redaction', False)

        self.enable_redaction = enable_redaction
        self._redactor = None

        if enable_redaction:
            self._redactor = get_redactor()

        # Read snapshot frequency from config
        self.snapshot_frequency = config.get('snapshot_frequency', 10)

    def create_session(
        self,
        title: str,
        provider: str,
        model: str,
        source: str,
        working_dir: Optional[Path] = None,
    ) -> Session:
        """Create a new session"""

        # Generate session ID
        timestamp = datetime.now().isoformat()
        session_id = f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hashlib.md5(timestamp.encode()).hexdigest()[:8]}"

        # Detect git repo if working_dir provided
        git_repo = None
        if working_dir:
            git_repo = self._detect_git_repo(working_dir)

        metadata = SessionMetadata(
            session_id=session_id,
            title=title,
            created=datetime.now(),
            last_active=datetime.now(),
            provider=provider,
            primary_model=model,
            source=source,
        )

        session = Session(metadata=metadata, git_repo=git_repo)

        # Create session directory (including parent sessions_dir if needed)
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "turns").mkdir(exist_ok=True)

        # Save metadata
        self._save_session_metadata(session)

        return session

    def _detect_git_repo(self, working_dir: Path) -> Optional[GitRepo]:
        """Detect git repository information"""
        try:
            # Check if git repo
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                cwd=working_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return None

            # Get current commit
            commit_result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=working_dir,
                capture_output=True,
                text=True,
            )

            # Empty repo: git init with no commits
            if commit_result.returncode != 0:
                # HEAD doesn't exist yet - this is an empty repo
                return GitRepo(
                    path=str(working_dir.absolute()),
                    remote=None,
                    base_commit=None,  # No commits yet
                    base_branch="main",  # Default branch (Git 2.28+)
                    is_clean=True,  # Empty repo is "clean"
                    uncommitted_files=[],
                )

            commit = commit_result.stdout.strip()

            # Sanity check: commit should be a valid SHA (40 hex chars for full, or shorter)
            # Not a literal "HEAD" string
            if commit == "HEAD" or not all(c in '0123456789abcdef' for c in commit.lower()):
                # Invalid commit hash - treat as empty repo
                return GitRepo(
                    path=str(working_dir.absolute()),
                    remote=None,
                    base_commit=None,
                    base_branch="main",
                    is_clean=True,
                    uncommitted_files=[],
                )

            # Get current branch
            branch = subprocess.run(
                ['git', 'branch', '--show-current'],
                cwd=working_dir,
                capture_output=True,
                text=True,
            ).stdout.strip() or "main"

            # Get remote
            remote = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=working_dir,
                capture_output=True,
                text=True,
            ).stdout.strip() or None

            # Check if clean
            status = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=working_dir,
                capture_output=True,
                text=True,
            ).stdout

            is_clean = len(status) == 0
            uncommitted = [line.strip() for line in status.splitlines()]

            return GitRepo(
                path=str(working_dir.absolute()),
                remote=remote,
                base_commit=commit,
                base_branch=branch,
                is_clean=is_clean,
                uncommitted_files=uncommitted,
            )

        except Exception:
            return None

    def commit_turn(
        self,
        session: Session,
        user_message: str,
        assistant_message: str,
        model: str,
        provider: str,
        file_operations: list[FileOperation] = None,
        state: Optional[StateBlock] = None,
        workspace_snapshot: Optional[dict] = None,
    ) -> Turn:
        """
        Commit a new turn to the session

        Args:
            session: Session to commit to
            user_message: User's prompt
            assistant_message: AI's response
            model: Model used
            provider: Provider (anthropic, openai, etc.)
            file_operations: List of file operations performed
            state: Current state block
            workspace_snapshot: Current workspace state (path -> hash)

        Returns:
            Created Turn object
        """

        turn_number = session.metadata.total_turns + 1

        # Get parent commit
        parent_commit = None
        if session.turns:
            # Turns are loaded in memory
            parent_commit = session.turns[-1].commit_id
        elif session.metadata.total_turns > 0:
            # Turns not loaded - read last turn from disk
            session_dir = self.sessions_dir / session.metadata.session_id
            last_turn_file = session_dir / "turns" / f"{session.metadata.total_turns:04d}.json"
            if last_turn_file.exists():
                with open(last_turn_file) as f:
                    last_turn_data = json.load(f)
                    parent_commit = last_turn_data.get('commit_id')

        # Create turn
        now = datetime.now()

        # Redact secrets if enabled
        if self.enable_redaction and self._redactor:
            user_message, _ = self._redactor.redact(user_message)
            assistant_message, _ = self._redactor.redact(assistant_message)

            # Also redact state block if provided
            if state:
                state.goal, _ = self._redactor.redact(state.goal)
                state.next_step, _ = self._redactor.redact(state.next_step)
                state.context_summary, _ = self._redactor.redact(state.context_summary)

                # Redact lists
                if state.decisions:
                    state.decisions = [self._redactor.redact(d)[0] for d in state.decisions]
                if state.open_questions:
                    state.open_questions = [self._redactor.redact(q)[0] for q in state.open_questions]

        turn = Turn(
            turn=turn_number,
            session_id=session.metadata.session_id,
            commit_id=self._generate_commit_id(session.metadata.session_id, turn_number),
            parent_commit=parent_commit,
            timestamp=now,
            user_input=UserInput(content=user_message, timestamp=now),
            assistant_output=AssistantOutput(
                content=assistant_message,
                timestamp=now,
                model=model,
                provider=provider,
            ),
            file_operations=file_operations or [],
            state=state or self._empty_state(),
            workspace_snapshot=workspace_snapshot or {},
        )

        # Save turn to disk
        self._save_turn(session, turn)

        # Update session metadata
        session.metadata.total_turns = turn_number
        session.metadata.last_active = now
        session.turns.append(turn)

        self._save_session_metadata(session)

        # Create snapshot at configured frequency
        if self.snapshot_frequency > 0 and turn_number % self.snapshot_frequency == 0:
            self._create_snapshot(session, turn_number)

        return turn

    def _generate_commit_id(self, session_id: str, turn: int) -> str:
        """Generate unique commit ID"""
        content = f"{session_id}:{turn}:{datetime.now().isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _empty_state(self) -> StateBlock:
        """Create empty state block"""
        return StateBlock(
            goal="",
            next_step="",
            context_summary="",
        )

    def _save_turn(self, session: Session, turn: Turn):
        """Save turn to disk"""
        session_dir = self.sessions_dir / session.metadata.session_id
        turn_file = session_dir / "turns" / f"{turn.turn:04d}.json"

        with open(turn_file, 'w') as f:
            json.dump(turn.model_dump(), f, indent=2, default=str)

    def _save_session_metadata(self, session: Session):
        """Save session metadata"""
        session_dir = self.sessions_dir / session.metadata.session_id
        meta_file = session_dir / "meta.json"

        data = {
            'metadata': session.metadata.model_dump(),
            'git_repo': session.git_repo.model_dump() if session.git_repo else None,
        }

        with open(meta_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def _create_snapshot(self, session: Session, up_to_turn: int):
        """Create snapshot for fast resume"""
        session_dir = self.sessions_dir / session.metadata.session_id
        snapshots_dir = session_dir / "snapshots"
        snapshots_dir.mkdir(exist_ok=True)

        snapshot_file = snapshots_dir / f"turn_{up_to_turn:04d}.json"

        # Get last 5 turns
        recent_turns = [t for t in session.turns if t.turn > up_to_turn - 5]

        snapshot = {
            'session_id': session.metadata.session_id,
            'up_to_turn': up_to_turn,
            'created': datetime.now().isoformat(),
            'state': session.current_state().model_dump() if session.current_state() else None,
            'recent_turns': [t.model_dump() for t in recent_turns],
        }

        with open(snapshot_file, 'w') as f:
            json.dump(snapshot, f, indent=2, default=str)

    def _try_load_from_snapshot(self, session: Session, session_dir: Path, total_turns: int) -> bool:
        """
        Try to recover cursor state from the most recent snapshot

        Returns True if snapshot was loaded successfully
        """
        snapshots_dir = session_dir / "snapshots"

        if not snapshots_dir.exists():
            return False

        # Find the most recent snapshot (could be at turn 10, 20, 30, etc.)
        snapshot_files = sorted(snapshots_dir.glob("turn_*.json"), reverse=True)

        for snapshot_file in snapshot_files:
            try:
                with open(snapshot_file) as f:
                    snapshot_data = json.load(f)

                # Extract state from snapshot
                if snapshot_data.get('state'):
                    state = StateBlock(**snapshot_data['state'])

                    # Try to load the last turn from snapshot's recent_turns
                    recent_turns = snapshot_data.get('recent_turns', [])
                    if recent_turns:
                        # Use the most recent turn from snapshot
                        last_turn_data = recent_turns[-1]
                        turn = Turn(**last_turn_data)
                        session.turns.append(turn)
                        return True

                    # No turns in snapshot but we have state - create a minimal turn
                    # This shouldn't normally happen but handle gracefully
                    return False

            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"Warning: Could not load snapshot {snapshot_file.name}: {e}", file=sys.stderr)
                continue

        return False

    def load_session(self, session_id: str, load_all_turns: bool = False) -> Optional[Session]:
        """
        Load a session from disk

        Args:
            session_id: Session ID to load
            load_all_turns: Whether to load all turns (can be slow for large sessions)
                          Note: Even with load_all_turns=False, the last turn is loaded
                          to populate current_state()

        Returns:
            Session object or None if not found
        """
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            return None

        # Load metadata
        meta_file = session_dir / "meta.json"
        with open(meta_file) as f:
            data = json.load(f)

        metadata = SessionMetadata(**data['metadata'])
        git_repo = GitRepo(**data['git_repo']) if data.get('git_repo') else None

        session = Session(metadata=metadata, git_repo=git_repo)

        if load_all_turns:
            # Load all turns
            turns_dir = session_dir / "turns"
            for turn_file in sorted(turns_dir.glob("*.json")):
                try:
                    with open(turn_file) as f:
                        turn_data = json.load(f)
                        session.turns.append(Turn(**turn_data))
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    # Skip broken turn files - log warning but don't crash
                    print(f"Warning: Could not load turn file {turn_file.name}: {e}", file=sys.stderr)
                    continue
        else:
            # Even without load_all_turns, load the LAST turn to get current_state()
            # This allows fast browsing while still having the cursor
            if metadata.total_turns > 0:
                turns_dir = session_dir / "turns"
                last_turn_file = turns_dir / f"{metadata.total_turns:04d}.json"
                turn_loaded = False

                if last_turn_file.exists():
                    try:
                        with open(last_turn_file) as f:
                            turn_data = json.load(f)
                            session.turns.append(Turn(**turn_data))
                            turn_loaded = True
                    except (json.JSONDecodeError, KeyError, TypeError) as e:
                        print(f"Warning: Could not load last turn {last_turn_file.name}: {e}", file=sys.stderr)

                # If last turn failed, try fallbacks in order of freshness:
                # 1. Previous turn (fresher than snapshot)
                # 2. Snapshot (older but might work if recent turns are all corrupt)
                if not turn_loaded:
                    # Try previous turn first (fresher data)
                    if metadata.total_turns > 1:
                        prev_turn_file = turns_dir / f"{metadata.total_turns - 1:04d}.json"
                        if prev_turn_file.exists():
                            try:
                                with open(prev_turn_file) as f:
                                    turn_data = json.load(f)
                                    session.turns.append(Turn(**turn_data))
                                    turn_loaded = True
                                    print(f"Info: Using previous turn for cursor state", file=sys.stderr)
                            except (json.JSONDecodeError, KeyError, TypeError):
                                pass  # Will try snapshot next

                    # If previous turn also failed, try snapshot
                    if not turn_loaded:
                        snapshot_loaded = self._try_load_from_snapshot(session, session_dir, metadata.total_turns)

                        if snapshot_loaded:
                            print(f"Info: Recovered cursor state from snapshot", file=sys.stderr)
                        else:
                            print(f"Warning: No cursor state available (recent turns and snapshot corrupted)", file=sys.stderr)

        return session

    def list_sessions(self, status: Optional[str] = None) -> list[Session]:
        """
        List all sessions

        Args:
            status: Filter by status (active, archived, etc.)

        Returns:
            List of sessions (metadata only, turns not loaded)
        """
        sessions = []

        # Check if sessions directory exists
        if not self.sessions_dir.exists():
            return []

        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue

            try:
                session = self.load_session(session_dir.name, load_all_turns=False)
                if session and (status is None or session.metadata.status == status):
                    sessions.append(session)
            except Exception:
                # Skip corrupted sessions
                continue

        # Sort by last_active (most recent first)
        sessions.sort(key=lambda s: s.metadata.last_active, reverse=True)

        return sessions

    def archive_session(self, session_id: str):
        """Archive a session"""
        session = self.load_session(session_id)
        if session:
            session.metadata.status = "archived"
            self._save_session_metadata(session)

            # Update search index if it exists
            search_db = self.storage_path / "search.db"
            if search_db.exists():
                try:
                    from .search import get_search_engine
                    search_engine = get_search_engine(self.storage_path)
                    # Update metadata in search index
                    import sqlite3
                    conn = sqlite3.connect(search_db)
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE session_metadata SET status = ? WHERE session_id = ?",
                        ("archived", session_id)
                    )
                    conn.commit()
                    conn.close()
                except Exception:
                    # If search update fails, don't break archiving
                    pass

    def delete_session(self, session_id: str):
        """Delete a session completely"""
        import shutil

        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)
