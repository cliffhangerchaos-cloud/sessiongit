"""
Simplified session models using dataclasses (no pydantic dependency for testing)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import json


@dataclass
class UserInput:
    """User's input in a turn"""
    content: str
    timestamp: datetime
    attachments: List[dict] = field(default_factory=list)

    def model_dump(self):
        return {
            'content': self.content,
            'timestamp': self.timestamp.isoformat(),
            'attachments': self.attachments,
        }


@dataclass
class AssistantOutput:
    """AI assistant's output in a turn"""
    content: str
    timestamp: datetime
    model: str
    provider: str
    tokens: Optional[dict] = None
    finish_reason: str = "stop"

    def model_dump(self):
        return {
            'content': self.content,
            'timestamp': self.timestamp.isoformat(),
            'model': self.model,
            'provider': self.provider,
            'tokens': self.tokens,
            'finish_reason': self.finish_reason,
        }


@dataclass
class FileOperation:
    """A file operation (read, write, delete)"""
    type: str
    path: str
    timestamp: datetime
    hash_before: Optional[str] = None
    hash_after: Optional[str] = None
    unified_diff: Optional[str] = None
    lines_added: int = 0
    lines_removed: int = 0
    git_tracked: bool = False
    git_base_hash: Optional[str] = None

    def model_dump(self):
        return {
            'type': self.type,
            'path': self.path,
            'timestamp': self.timestamp.isoformat(),
            'hash_before': self.hash_before,
            'hash_after': self.hash_after,
            'unified_diff': self.unified_diff,
            'lines_added': self.lines_added,
            'lines_removed': self.lines_removed,
            'git_tracked': self.git_tracked,
            'git_base_hash': self.git_base_hash,
        }


@dataclass
class StateBlock:
    """The 'cursor' - where we are in the session"""
    goal: str
    next_step: str
    context_summary: str
    completed_this_turn: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    key_insights: List[str] = field(default_factory=list)
    working_files: List[str] = field(default_factory=list)
    working_directory: Optional[str] = None
    git_branch: Optional[str] = None

    def model_dump(self):
        return {
            'goal': self.goal,
            'next_step': self.next_step,
            'context_summary': self.context_summary,
            'completed_this_turn': self.completed_this_turn,
            'decisions': self.decisions,
            'open_questions': self.open_questions,
            'key_insights': self.key_insights,
            'working_files': self.working_files,
            'working_directory': self.working_directory,
            'git_branch': self.git_branch,
        }


@dataclass
class Turn:
    """One turn (user prompt + AI response + actions)"""
    turn: int
    session_id: str
    commit_id: str
    parent_commit: Optional[str]
    timestamp: datetime
    user_input: UserInput
    assistant_output: AssistantOutput
    state: StateBlock
    file_operations: List[FileOperation] = field(default_factory=list)
    command_executions: List[dict] = field(default_factory=list)
    workspace_snapshot: Dict[str, str] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def model_dump(self):
        return {
            'turn': self.turn,
            'session_id': self.session_id,
            'commit_id': self.commit_id,
            'parent_commit': self.parent_commit,
            'timestamp': self.timestamp.isoformat(),
            'user_input': self.user_input.model_dump(),
            'assistant_output': self.assistant_output.model_dump(),
            'state': self.state.model_dump(),
            'file_operations': [op.model_dump() for op in self.file_operations],
            'command_executions': self.command_executions,
            'workspace_snapshot': self.workspace_snapshot,
            'metadata': self.metadata,
        }


@dataclass
class SessionMetadata:
    """Session metadata"""
    session_id: str
    title: str
    created: datetime
    last_active: datetime
    provider: str
    primary_model: str
    source: str
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    status: str = "active"
    total_turns: int = 0
    total_tokens: int = 0

    def model_dump(self):
        return {
            'session_id': self.session_id,
            'title': self.title,
            'description': self.description,
            'tags': self.tags,
            'created': self.created.isoformat(),
            'last_active': self.last_active.isoformat(),
            'status': self.status,
            'provider': self.provider,
            'primary_model': self.primary_model,
            'source': self.source,
            'total_turns': self.total_turns,
            'total_tokens': self.total_tokens,
        }


@dataclass
class GitRepo:
    """Git repository information"""
    path: str
    base_commit: Optional[str] = None  # None for empty repos (no commits yet)
    base_branch: str
    is_clean: bool
    remote: Optional[str] = None
    uncommitted_files: List[str] = field(default_factory=list)

    def model_dump(self):
        return {
            'path': self.path,
            'remote': self.remote,
            'base_commit': self.base_commit,
            'base_branch': self.base_branch,
            'is_clean': self.is_clean,
            'uncommitted_files': self.uncommitted_files,
        }


@dataclass
class Session:
    """Complete session"""
    metadata: SessionMetadata
    git_repo: Optional[GitRepo] = None
    turns: List[Turn] = field(default_factory=list)

    def current_state(self) -> Optional[StateBlock]:
        """Get current state from latest turn"""
        if not self.turns:
            return None
        return self.turns[-1].state

    def get_turn(self, turn_number: int) -> Optional[Turn]:
        """Get specific turn"""
        for turn in self.turns:
            if turn.turn == turn_number:
                return turn
        return None
