"""
Unit tests for data models
"""

import pytest
from datetime import datetime
from pydantic import ValidationError


@pytest.mark.unit
class TestModels:
    """Test Pydantic models"""

    def test_user_input_model(self):
        """Test UserInput model"""
        from sessiongit.models.session import UserInput

        user_input = UserInput(
            content="Test message",
            timestamp=datetime.now(),
        )

        assert user_input.content == "Test message"
        assert isinstance(user_input.timestamp, datetime)
        assert user_input.attachments == []

    def test_assistant_output_model(self):
        """Test AssistantOutput model"""
        from sessiongit.models.session import AssistantOutput

        output = AssistantOutput(
            content="Test response",
            timestamp=datetime.now(),
            model="claude-sonnet-4-5",
            provider="anthropic",
        )

        assert output.content == "Test response"
        assert output.model == "claude-sonnet-4-5"
        assert output.provider == "anthropic"
        assert output.finish_reason == "stop"  # default

    def test_file_operation_model(self):
        """Test FileOperation model"""
        from sessiongit.models.session import FileOperation

        op = FileOperation(
            type="file_write",
            path="/test/file.py",
            timestamp=datetime.now(),
            hash_before="abc123",
            hash_after="def456",
            unified_diff="@@ -1,1 +1,1 @@\n-old\n+new",
            lines_added=1,
            lines_removed=1,
        )

        assert op.type == "file_write"
        assert op.path == "/test/file.py"
        assert op.hash_before == "abc123"
        assert op.hash_after == "def456"

    def test_state_block_model(self):
        """Test StateBlock model"""
        from sessiongit.models.session import StateBlock

        state = StateBlock(
            goal="Fix bug",
            next_step="Test fix",
            context_summary="Working on authentication",
        )

        assert state.goal == "Fix bug"
        assert state.next_step == "Test fix"
        assert state.decisions == []  # default
        assert state.open_questions == []  # default

    def test_state_block_with_data(self):
        """Test StateBlock with all fields"""
        from sessiongit.models.session import StateBlock

        state = StateBlock(
            goal="Fix JWT authentication",
            completed_this_turn=["Changed expiry"],
            decisions=["Use 2-hour expiry"],
            open_questions=["Should we add refresh tokens?"],
            next_step="Test the changes",
            context_summary="Debugging timeout issues",
            key_insights=["Expiry was too short"],
            working_files=["auth.py", "config.yml"],
            working_directory="/project",
            git_branch="fix/auth",
        )

        assert len(state.decisions) == 1
        assert len(state.open_questions) == 1
        assert len(state.working_files) == 2

    def test_session_metadata_model(self):
        """Test SessionMetadata model"""
        from sessiongit.models.session import SessionMetadata

        meta = SessionMetadata(
            session_id="sess_123",
            title="Test Session",
            created=datetime.now(),
            last_active=datetime.now(),
            provider="anthropic",
            primary_model="claude-sonnet-4-5",
            source="test",
        )

        assert meta.session_id == "sess_123"
        assert meta.title == "Test Session"
        assert meta.status == "active"  # default
        assert meta.total_turns == 0  # default

    def test_git_repo_model(self):
        """Test GitRepo model"""
        from sessiongit.models.session import GitRepo

        repo = GitRepo(
            path="/project",
            remote="git@github.com:user/repo.git",
            base_commit="abc123",
            base_branch="main",
            is_clean=True,
        )

        assert repo.path == "/project"
        assert repo.remote == "git@github.com:user/repo.git"
        assert repo.is_clean

    def test_turn_model(self):
        """Test Turn model"""
        from sessiongit.models.session import Turn, UserInput, AssistantOutput, StateBlock

        now = datetime.now()

        turn = Turn(
            turn=1,
            session_id="sess_123",
            commit_id="commit_abc",
            parent_commit=None,
            timestamp=now,
            user_input=UserInput(content="Test", timestamp=now),
            assistant_output=AssistantOutput(
                content="Response",
                timestamp=now,
                model="claude-sonnet-4-5",
                provider="anthropic",
            ),
            state=StateBlock(
                goal="Test",
                next_step="Continue",
                context_summary="Testing",
            ),
        )

        assert turn.turn == 1
        assert turn.session_id == "sess_123"
        assert turn.user_input.content == "Test"
        assert turn.assistant_output.content == "Response"

    def test_session_model(self):
        """Test Session model"""
        from sessiongit.models.session import Session, SessionMetadata

        meta = SessionMetadata(
            session_id="sess_123",
            title="Test",
            created=datetime.now(),
            last_active=datetime.now(),
            provider="anthropic",
            primary_model="claude-sonnet-4-5",
            source="test",
        )

        session = Session(metadata=meta)

        assert session.metadata.session_id == "sess_123"
        assert session.turns == []
        assert session.git_repo is None

    def test_model_validation(self):
        """Test that models validate required fields"""
        from sessiongit.models.session import StateBlock

        # Missing required fields should raise ValidationError
        with pytest.raises(ValidationError):
            StateBlock()  # Missing goal, next_step, context_summary

    def test_model_serialization(self):
        """Test model serialization to dict"""
        from sessiongit.models.session import StateBlock

        state = StateBlock(
            goal="Test goal",
            next_step="Test step",
            context_summary="Test summary",
            decisions=["Decision 1", "Decision 2"],
        )

        # Serialize
        data = state.model_dump()

        assert data['goal'] == "Test goal"
        assert data['next_step'] == "Test step"
        assert len(data['decisions']) == 2

    def test_model_deserialization(self):
        """Test creating model from dict"""
        from sessiongit.models.session import StateBlock

        data = {
            'goal': "Test goal",
            'next_step': "Test step",
            'context_summary': "Test summary",
            'decisions': ["Decision 1"],
            'open_questions': [],
            'completed_this_turn': [],
            'key_insights': [],
            'working_files': [],
            'working_directory': None,
            'git_branch': None,
        }

        state = StateBlock(**data)

        assert state.goal == "Test goal"
        assert len(state.decisions) == 1
