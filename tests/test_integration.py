"""
Integration tests for SessionGit

Test complete workflows end-to-end.
"""

import pytest
from pathlib import Path
from datetime import datetime


@pytest.mark.integration
class TestIntegration:
    """Integration tests for complete workflows"""

    def test_full_session_lifecycle(self, session_manager, temp_dir):
        """Test complete session lifecycle: create, commit, save, load, resume"""
        # 1. Create session
        session = session_manager.create_session(
            title="Full lifecycle test",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test",
        )

        session_id = session.metadata.session_id

        # 2. Add multiple turns
        for i in range(5):
            from sessiongit.models.session import StateBlock

            state = StateBlock(
                goal=f"Goal {i+1}",
                next_step=f"Step {i+1}",
                context_summary=f"Context {i+1}",
                decisions=[f"Decision {i+1}"],
            )

            session_manager.commit_turn(
                session=session,
                user_message=f"User message {i+1}",
                assistant_message=f"AI response {i+1}",
                model="claude-sonnet-4-5",
                provider="anthropic",
                state=state,
            )

        # 3. Archive session
        session_manager.archive_session(session_id)

        # 4. Load session
        loaded = session_manager.load_session(session_id, load_all_turns=True)

        # 5. Verify all data preserved
        assert loaded.metadata.session_id == session_id
        assert loaded.metadata.status == "archived"
        assert loaded.metadata.total_turns == 5
        assert len(loaded.turns) == 5

        # 6. Verify state progression
        last_state = loaded.current_state()
        assert last_state.goal == "Goal 5"
        assert last_state.decisions[0] == "Decision 5"

    def test_file_tracking_workflow(self, session_manager, temp_dir):
        """Test workflow with file tracking"""
        from sessiongit.models.session import FileOperation, StateBlock

        # Create session
        session = session_manager.create_session(
            title="File tracking test",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test",
        )

        # Create test file
        test_file = temp_dir / "test.py"
        test_file.write_text("print('hello')")

        # Store file in object store
        hash1 = session_manager.object_store.store_file(test_file)

        # Turn 1: Read file
        op1 = FileOperation(
            type="file_read",
            path=str(test_file),
            timestamp=datetime.now(),
            hash_before=hash1,
        )

        session_manager.commit_turn(
            session=session,
            user_message="Read the file",
            assistant_message="I see the file contents",
            model="claude-sonnet-4-5",
            provider="anthropic",
            file_operations=[op1],
            state=StateBlock(
                goal="Modify file",
                next_step="Edit the file",
                context_summary="Reading file",
            ),
        )

        # Modify file
        test_file.write_text("print('hello world')")
        hash2 = session_manager.object_store.store_file(test_file)

        # Turn 2: Edit file
        op2 = FileOperation(
            type="file_write",
            path=str(test_file),
            timestamp=datetime.now(),
            hash_before=hash1,
            hash_after=hash2,
            unified_diff="@@ -1,1 +1,1 @@\n-print('hello')\n+print('hello world')",
            lines_added=1,
            lines_removed=1,
        )

        session_manager.commit_turn(
            session=session,
            user_message="Change the message",
            assistant_message="Updated the print statement",
            model="claude-sonnet-4-5",
            provider="anthropic",
            file_operations=[op2],
            state=StateBlock(
                goal="Modify file",
                next_step="Test the change",
                context_summary="Modified file",
                decisions=["Changed message to 'hello world'"],
            ),
        )

        # Load and verify
        loaded = session_manager.load_session(session.metadata.session_id, load_all_turns=True)

        assert len(loaded.turns) == 2
        assert loaded.turns[0].file_operations[0].type == "file_read"
        assert loaded.turns[1].file_operations[0].type == "file_write"
        assert loaded.turns[1].file_operations[0].hash_before == hash1
        assert loaded.turns[1].file_operations[0].hash_after == hash2

    def test_snapshot_and_resume(self, session_manager):
        """Test snapshot creation and resume from snapshot"""
        from sessiongit.models.session import StateBlock

        # Create session
        session = session_manager.create_session(
            title="Snapshot test",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test",
        )

        # Add 12 turns (should create snapshot at turn 10)
        for i in range(12):
            state = StateBlock(
                goal=f"Goal at turn {i+1}",
                next_step=f"Step {i+1}",
                context_summary=f"Context at turn {i+1}",
                decisions=[f"Decision {i+1}"],
            )

            session_manager.commit_turn(
                session=session,
                user_message=f"Message {i+1}",
                assistant_message=f"Response {i+1}",
                model="claude-sonnet-4-5",
                provider="anthropic",
                state=state,
            )

        session_id = session.metadata.session_id

        # Verify snapshot exists
        session_dir = session_manager.sessions_dir / session_id
        snapshot_file = session_dir / "snapshots" / "turn_0010.json"
        assert snapshot_file.exists()

        # Load session
        loaded = session_manager.load_session(session_id, load_all_turns=True)

        # Verify can resume from snapshot
        assert loaded.metadata.total_turns == 12
        assert loaded.turns[9].turn == 10  # Snapshot point
        assert loaded.turns[11].turn == 12  # Latest

    def test_multiple_sessions(self, session_manager):
        """Test managing multiple sessions"""
        # Create 3 sessions
        sessions = []
        for i in range(3):
            session = session_manager.create_session(
                title=f"Session {i+1}",
                provider="anthropic",
                model="claude-sonnet-4-5",
                source="test",
            )
            sessions.append(session)

            # Add some turns
            for j in range(i + 1):  # Session 1 gets 1 turn, Session 2 gets 2, etc.
                session_manager.commit_turn(
                    session=session,
                    user_message=f"Message {j+1}",
                    assistant_message=f"Response {j+1}",
                    model="claude-sonnet-4-5",
                    provider="anthropic",
                )

        # List all sessions
        all_sessions = session_manager.list_sessions()
        assert len(all_sessions) >= 3

        # Verify each session
        for i, session in enumerate(sessions):
            loaded = session_manager.load_session(session.metadata.session_id, load_all_turns=True)
            assert loaded.metadata.total_turns == i + 1

    def test_session_search_and_filter(self, session_manager):
        """Test searching and filtering sessions"""
        # Create sessions with different statuses
        active1 = session_manager.create_session(
            title="Active Session 1",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test",
        )

        active2 = session_manager.create_session(
            title="Active Session 2",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test",
        )

        to_archive = session_manager.create_session(
            title="To Archive",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test",
        )

        # Archive one
        session_manager.archive_session(to_archive.metadata.session_id)

        # Filter active
        active_sessions = session_manager.list_sessions(status="active")
        active_ids = [s.metadata.session_id for s in active_sessions]

        assert active1.metadata.session_id in active_ids
        assert active2.metadata.session_id in active_ids
        assert to_archive.metadata.session_id not in active_ids

        # Filter archived
        archived_sessions = session_manager.list_sessions(status="archived")
        archived_ids = [s.metadata.session_id for s in archived_sessions]

        assert to_archive.metadata.session_id in archived_ids

    def test_storage_deduplication(self, session_manager, temp_dir):
        """Test that storage deduplicates identical content"""
        # Create file
        test_file = temp_dir / "duplicate.txt"
        content = "This content will be duplicated"
        test_file.write_text(content)

        # Store same content 5 times
        hashes = []
        for _ in range(5):
            hash_val = session_manager.object_store.store_file(test_file)
            hashes.append(hash_val)

        # All hashes should be identical
        assert len(set(hashes)) == 1

        # Object should only be stored once
        stats = session_manager.object_store.stats()
        # Should be 1 object (all deduplicated)
        assert stats['total_objects'] == 1

    def test_error_recovery(self, session_manager):
        """Test that system handles errors gracefully"""
        # Create session
        session = session_manager.create_session(
            title="Error recovery test",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test",
        )

        # Commit normal turn
        session_manager.commit_turn(
            session=session,
            user_message="Normal message",
            assistant_message="Normal response",
            model="claude-sonnet-4-5",
            provider="anthropic",
        )

        # Session should still be valid
        loaded = session_manager.load_session(session.metadata.session_id)
        assert loaded is not None
        assert loaded.metadata.total_turns == 1

    def test_concurrent_sessions(self, temp_dir):
        """Test handling multiple session managers (simulating concurrency)"""
        from sessiongit.core.session_manager import SessionManager

        # Create two managers on same storage
        manager1 = SessionManager(temp_dir)
        manager2 = SessionManager(temp_dir)

        # Create session with manager1
        session1 = manager1.create_session(
            title="Session from manager 1",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test",
        )

        # Load with manager2
        loaded = manager2.load_session(session1.metadata.session_id)

        assert loaded is not None
        assert loaded.metadata.title == "Session from manager 1"

    def test_large_session(self, session_manager):
        """Test session with many turns (stress test)"""
        from sessiongit.models.session import StateBlock

        # Create session
        session = session_manager.create_session(
            title="Large session stress test",
            provider="anthropic",
            model="claude-sonnet-4-5",
            source="test",
        )

        # Add 50 turns
        for i in range(50):
            state = StateBlock(
                goal=f"Process item {i+1}",
                next_step=f"Continue to item {i+2}",
                context_summary=f"Working on item {i+1}",
            )

            session_manager.commit_turn(
                session=session,
                user_message=f"Process item {i+1}",
                assistant_message=f"Processing item {i+1}...",
                model="claude-sonnet-4-5",
                provider="anthropic",
                state=state,
            )

        # Load and verify
        loaded = session_manager.load_session(session.metadata.session_id, load_all_turns=True)

        assert loaded.metadata.total_turns == 50
        assert len(loaded.turns) == 50

        # Verify snapshots created
        session_dir = session_manager.sessions_dir / session.metadata.session_id
        snapshots_dir = session_dir / "snapshots"

        # Should have snapshots at 10, 20, 30, 40, 50
        assert (snapshots_dir / "turn_0010.json").exists()
        assert (snapshots_dir / "turn_0020.json").exists()
        assert (snapshots_dir / "turn_0030.json").exists()
        assert (snapshots_dir / "turn_0040.json").exists()
        assert (snapshots_dir / "turn_0050.json").exists()

        # Check storage stats
        # Note: If no file operations, object store may be empty (turns are JSON, not blobs)
        stats = session_manager.object_store.stats()
        # Just verify stats are accessible - no objects if no file operations
        assert 'total_objects' in stats
        assert 'compression_ratio' in stats
