"""
Unit tests for SessionManager
"""

import pytest
from pathlib import Path
from datetime import datetime


@pytest.mark.unit
class TestSessionManager:
    """Test SessionManager functionality"""

    def test_init_does_not_create_directories(self, temp_dir):
        """Test that SessionManager does not create directories on init"""
        from sessiongit.core.session_manager import SessionManager

        manager = SessionManager(temp_dir)

        # v0.1.1: directories are created on first write, not on construction
        assert not (temp_dir / "sessions").exists()
        # objects/ is never auto-created, even on write

        # But sessions/ should be created when creating a session
        session = manager.create_session(
            title="Test",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test"
        )
        assert (temp_dir / "sessions").exists()
        assert (temp_dir / "sessions" / session.metadata.session_id).exists()

    def test_create_session(self, session_manager, sample_session_data):
        """Test creating a new session"""
        session = session_manager.create_session(**sample_session_data)

        assert session is not None
        assert session.metadata.session_id.startswith("sess_")
        assert session.metadata.title == sample_session_data["title"]
        assert session.metadata.provider == sample_session_data["provider"]
        assert session.metadata.total_turns == 0

        # Verify session directory exists
        session_dir = session_manager.sessions_dir / session.metadata.session_id
        assert session_dir.exists()
        assert (session_dir / "meta.json").exists()
        assert (session_dir / "turns").exists()

    def test_commit_turn(self, session_manager, sample_session_data, sample_turn_data):
        """Test committing a turn to a session"""
        # Create session
        session = session_manager.create_session(**sample_session_data)

        # Commit turn
        turn = session_manager.commit_turn(session=session, **sample_turn_data)

        assert turn is not None
        assert turn.turn == 1
        assert turn.session_id == session.metadata.session_id
        assert turn.user_input.content == sample_turn_data["user_message"]
        assert turn.assistant_output.content == sample_turn_data["assistant_message"]

        # Verify session updated
        assert session.metadata.total_turns == 1
        assert len(session.turns) == 1

        # Verify turn file created
        session_dir = session_manager.sessions_dir / session.metadata.session_id
        turn_file = session_dir / "turns" / "0001.json"
        assert turn_file.exists()

    def test_commit_multiple_turns(self, session_manager, sample_session_data, sample_turn_data):
        """Test committing multiple turns"""
        session = session_manager.create_session(**sample_session_data)

        # Commit 5 turns
        for i in range(5):
            turn = session_manager.commit_turn(
                session=session,
                user_message=f"Message {i+1}",
                assistant_message=f"Response {i+1}",
                model=sample_turn_data["model"],
                provider=sample_turn_data["provider"],
            )
            assert turn.turn == i + 1

        assert session.metadata.total_turns == 5
        assert len(session.turns) == 5

    def test_turn_commit_id_generation(self, session_manager, sample_session_data, sample_turn_data):
        """Test that commit IDs are generated and linked"""
        session = session_manager.create_session(**sample_session_data)

        # First turn
        turn1 = session_manager.commit_turn(session=session, **sample_turn_data)
        assert turn1.commit_id is not None
        assert turn1.parent_commit is None  # First turn has no parent

        # Second turn
        turn2 = session_manager.commit_turn(session=session, **sample_turn_data)
        assert turn2.commit_id is not None
        assert turn2.parent_commit == turn1.commit_id  # Linked to previous

    def test_load_session(self, session_manager, sample_session_data):
        """Test loading a session from disk"""
        # Create session
        session = session_manager.create_session(**sample_session_data)
        session_id = session.metadata.session_id

        # Load it back
        loaded = session_manager.load_session(session_id, load_all_turns=False)

        assert loaded is not None
        assert loaded.metadata.session_id == session_id
        assert loaded.metadata.title == sample_session_data["title"]

    def test_load_session_with_turns(self, session_manager, sample_session_data, sample_turn_data):
        """Test loading session with all turns"""
        # Create session and add turns
        session = session_manager.create_session(**sample_session_data)

        for i in range(3):
            session_manager.commit_turn(
                session=session,
                user_message=f"Message {i+1}",
                assistant_message=f"Response {i+1}",
                model=sample_turn_data["model"],
                provider=sample_turn_data["provider"],
            )

        session_id = session.metadata.session_id

        # Load with turns
        loaded = session_manager.load_session(session_id, load_all_turns=True)

        assert loaded is not None
        assert len(loaded.turns) == 3
        assert loaded.turns[0].turn == 1
        assert loaded.turns[2].turn == 3

    def test_load_nonexistent_session(self, session_manager):
        """Test loading a session that doesn't exist"""
        loaded = session_manager.load_session("nonexistent_session")
        assert loaded is None

    def test_list_sessions(self, session_manager, sample_session_data):
        """Test listing all sessions"""
        # Create multiple sessions
        session1 = session_manager.create_session(title="Session 1", **{k: v for k, v in sample_session_data.items() if k != 'title'})
        session2 = session_manager.create_session(title="Session 2", **{k: v for k, v in sample_session_data.items() if k != 'title'})
        session3 = session_manager.create_session(title="Session 3", **{k: v for k, v in sample_session_data.items() if k != 'title'})

        # List all
        sessions = session_manager.list_sessions()

        assert len(sessions) >= 3
        session_ids = [s.metadata.session_id for s in sessions]
        assert session1.metadata.session_id in session_ids
        assert session2.metadata.session_id in session_ids
        assert session3.metadata.session_id in session_ids

    def test_list_sessions_by_status(self, session_manager, sample_session_data):
        """Test filtering sessions by status"""
        # Create sessions
        session1 = session_manager.create_session(title="Active", **{k: v for k, v in sample_session_data.items() if k != 'title'})
        session2 = session_manager.create_session(title="To Archive", **{k: v for k, v in sample_session_data.items() if k != 'title'})

        # Archive one
        session_manager.archive_session(session2.metadata.session_id)

        # List active only
        active = session_manager.list_sessions(status="active")
        active_ids = [s.metadata.session_id for s in active]

        assert session1.metadata.session_id in active_ids
        assert session2.metadata.session_id not in active_ids

        # List archived only
        archived = session_manager.list_sessions(status="archived")
        archived_ids = [s.metadata.session_id for s in archived]

        assert session2.metadata.session_id in archived_ids

    def test_archive_session(self, session_manager, sample_session_data):
        """Test archiving a session"""
        session = session_manager.create_session(**sample_session_data)
        session_id = session.metadata.session_id

        # Archive
        session_manager.archive_session(session_id)

        # Reload and check status
        loaded = session_manager.load_session(session_id)
        assert loaded.metadata.status == "archived"

    def test_delete_session(self, session_manager, sample_session_data):
        """Test deleting a session"""
        session = session_manager.create_session(**sample_session_data)
        session_id = session.metadata.session_id

        session_dir = session_manager.sessions_dir / session_id
        assert session_dir.exists()

        # Delete
        session_manager.delete_session(session_id)

        # Verify deleted
        assert not session_dir.exists()
        loaded = session_manager.load_session(session_id)
        assert loaded is None

    def test_snapshot_creation(self, session_manager, sample_session_data, sample_turn_data):
        """Test that snapshots are created every 10 turns"""
        session = session_manager.create_session(**sample_session_data)

        # Add 15 turns
        for i in range(15):
            session_manager.commit_turn(
                session=session,
                user_message=f"Message {i+1}",
                assistant_message=f"Response {i+1}",
                model=sample_turn_data["model"],
                provider=sample_turn_data["provider"],
            )

        # Check snapshots
        session_dir = session_manager.sessions_dir / session.metadata.session_id
        snapshots_dir = session_dir / "snapshots"

        assert snapshots_dir.exists()
        assert (snapshots_dir / "turn_0010.json").exists()
        # Turn 15 doesn't trigger snapshot (only multiples of 10)

    def test_git_repo_detection(self, session_manager, temp_dir):
        """Test git repository detection"""
        # This test will pass if git is not available
        session = session_manager.create_session(
            title="Git test",
            provider="test",
            model="test",
            source="test",
            working_dir=temp_dir,
        )

        # git_repo will be None if not a git repo or git not available
        # We just verify it doesn't crash
        assert session.git_repo is None or session.git_repo.path is not None

    def test_session_with_file_operations(self, session_manager, sample_session_data, sample_turn_data):
        """Test committing turn with file operations"""
        from sessiongit.models.session import FileOperation

        session = session_manager.create_session(**sample_session_data)

        # Create file operation
        file_op = FileOperation(
            type="file_write",
            path="/test/auth.py",
            timestamp=datetime.now(),
            hash_before=None,
            hash_after="abc123",
            unified_diff="@@ -1,1 +1,1 @@\n-old\n+new",
        )

        # Commit turn with file operation
        turn = session_manager.commit_turn(
            session=session,
            **sample_turn_data,
            file_operations=[file_op],
        )

        assert len(turn.file_operations) == 1
        assert turn.file_operations[0].type == "file_write"
        assert turn.file_operations[0].path == "/test/auth.py"

    def test_session_with_state(self, session_manager, sample_session_data, sample_turn_data):
        """Test committing turn with state block"""
        from sessiongit.models.session import StateBlock

        session = session_manager.create_session(**sample_session_data)

        # Create state
        state = StateBlock(
            goal="Fix authentication bug",
            next_step="Test the fix",
            context_summary="Working on JWT timeout issue",
            decisions=["Use 2-hour expiry"],
            open_questions=["Should we increase further?"],
        )

        # Commit with state
        turn = session_manager.commit_turn(
            session=session,
            **sample_turn_data,
            state=state,
        )

        assert turn.state.goal == "Fix authentication bug"
        assert len(turn.state.decisions) == 1
        assert turn.state.decisions[0] == "Use 2-hour expiry"

    def test_current_state(self, session_manager, sample_session_data, sample_turn_data):
        """Test getting current state from session"""
        from sessiongit.models.session import StateBlock

        session = session_manager.create_session(**sample_session_data)

        # No turns yet
        assert session.current_state() is None

        # Add turn with state
        state = StateBlock(
            goal="Test goal",
            next_step="Test step",
            context_summary="Test context",
        )

        session_manager.commit_turn(
            session=session,
            **sample_turn_data,
            state=state,
        )

        current = session.current_state()
        assert current is not None
        assert current.goal == "Test goal"
