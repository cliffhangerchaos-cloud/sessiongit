"""
Session and Turn data models
"""

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field
from pathlib import Path


class UserInput(BaseModel):
    """User's input in a turn"""
    content: str
    timestamp: datetime
    attachments: list[dict] = Field(default_factory=list)


class AssistantOutput(BaseModel):
    """AI assistant's output in a turn"""
    content: str
    timestamp: datetime
    model: str
    provider: str
    tokens: Optional[dict] = None
    finish_reason: str = "stop"


class FileOperation(BaseModel):
    """A file operation (read, write, delete)"""
    type: str  # 'file_read', 'file_write', 'file_delete'
    path: str
    timestamp: datetime

    # Before state
    hash_before: Optional[str] = None

    # After state (for writes)
    hash_after: Optional[str] = None

    # Diff (for edits)
    unified_diff: Optional[str] = None
    lines_added: int = 0
    lines_removed: int = 0

    # Git context
    git_tracked: bool = False
    git_base_hash: Optional[str] = None


class CommandExecution(BaseModel):
    """A command execution"""
    type: str = "bash_command"
    command: str
    timestamp: datetime
    working_dir: str

    exit_code: int
    duration_ms: int
    stdout: dict  # {size_bytes, storage, content/head/tail}
    stderr: dict


class StateBlock(BaseModel):
    """The 'cursor' - where we are in the session"""
    goal: str
    completed_this_turn: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_step: str
    context_summary: str
    key_insights: list[str] = Field(default_factory=list)

    working_files: list[str] = Field(default_factory=list)
    working_directory: Optional[str] = None
    git_branch: Optional[str] = None


class Turn(BaseModel):
    """One turn (user prompt + AI response + actions)"""
    turn: int
    session_id: str
    commit_id: str
    parent_commit: Optional[str]
    timestamp: datetime

    user_input: UserInput
    assistant_output: AssistantOutput

    file_operations: list[FileOperation] = Field(default_factory=list)
    command_executions: list[CommandExecution] = Field(default_factory=list)

    state: StateBlock

    # Workspace snapshot (all files at end of this turn)
    workspace_snapshot: dict[str, str] = Field(default_factory=dict)  # path -> hash

    metadata: dict = Field(default_factory=dict)


class SessionMetadata(BaseModel):
    """Session metadata"""
    session_id: str
    title: str
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    created: datetime
    last_active: datetime
    status: str = "active"  # active, archived, deleted

    provider: str
    primary_model: str
    source: str  # claude-desktop, chatgpt-web, etc.

    total_turns: int = 0
    total_tokens: int = 0


class GitRepo(BaseModel):
    """Git repository information"""
    path: str
    remote: Optional[str] = None
    base_commit: Optional[str] = None  # None for empty repos (no commits yet)
    base_branch: str
    is_clean: bool
    uncommitted_files: list[str] = Field(default_factory=list)


class Session(BaseModel):
    """Complete session"""
    metadata: SessionMetadata
    git_repo: Optional[GitRepo] = None

    # Loaded lazily
    turns: list[Turn] = Field(default_factory=list)

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
