"""
Tests for v0.2.0 features: Export/Import, Secret Redaction, Search
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from sessiongit.core.session_manager import SessionManager
from sessiongit.core.export_import import export_session, import_session
from sessiongit.core.secrets import SecretRedactor
from sessiongit.core.search import SessionSearch
from sessiongit.models.session import StateBlock


@pytest.fixture
def temp_storage():
    """Create temporary storage directory"""
    temp_dir = Path(tempfile.mkdtemp())
    (temp_dir / "sessions").mkdir()
    (temp_dir / "objects").mkdir()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def session_manager(temp_storage):
    """Create session manager"""
    return SessionManager(temp_storage)


@pytest.fixture
def sample_session(session_manager):
    """Create a sample session with turns"""
    session = session_manager.create_session(
        title="Test Session",
        provider="anthropic",
        model="claude-sonnet-4-5",
        source="test"
    )

    # Add some turns
    for i in range(3):
        session_manager.commit_turn(
            session=session,
            user_message=f"User message {i}",
            assistant_message=f"Assistant response {i}",
            model="claude-sonnet-4-5",
            provider="anthropic",
            state=StateBlock(
                goal=f"Test goal {i}",
                next_step=f"Next step {i}",
                context_summary=f"Context {i}"
            )
        )

    return session


class TestExportImport:
    """Test export and import functionality"""

    def test_export_session(self, session_manager, sample_session, temp_storage):
        """Test exporting a session"""
        output_path = temp_storage / "export.zip"

        stats = export_session(session_manager, sample_session.metadata.session_id, output_path)

        assert output_path.exists()
        assert stats['session_id'] == sample_session.metadata.session_id
        assert stats['total_turns'] == 3
        assert stats['files_exported'] > 0
        assert stats['size_bytes'] > 0

    def test_import_session(self, session_manager, sample_session, temp_storage):
        """Test importing a session"""
        # Export first
        export_path = temp_storage / "export.zip"
        export_session(session_manager, sample_session.metadata.session_id, export_path)

        # Create new storage for import
        import_storage = Path(tempfile.mkdtemp())
        (import_storage / "sessions").mkdir(parents=True)
        (import_storage / "objects").mkdir()

        try:
            import_manager = SessionManager(import_storage)

            # Import
            stats = import_session(import_manager, export_path)

            assert stats['session_id'] == sample_session.metadata.session_id
            assert stats['files_imported'] > 0

            # Verify imported session
            imported = import_manager.load_session(sample_session.metadata.session_id, load_all_turns=True)
            assert imported is not None
            assert imported.metadata.title == "Test Session"
            assert len(imported.turns) == 3

        finally:
            shutil.rmtree(import_storage)

    def test_import_with_rename(self, session_manager, sample_session, temp_storage):
        """Test importing with rename"""
        export_path = temp_storage / "export.zip"
        export_session(session_manager, sample_session.metadata.session_id, export_path)

        import_storage = Path(tempfile.mkdtemp())
        (import_storage / "sessions").mkdir(parents=True)
        (import_storage / "objects").mkdir()

        try:
            import_manager = SessionManager(import_storage)
            stats = import_session(import_manager, export_path, rename="Renamed Session")

            imported = import_manager.load_session(stats['session_id'], load_all_turns=False)
            assert imported.metadata.title == "Renamed Session"

        finally:
            shutil.rmtree(import_storage)


class TestSecretRedaction:
    """Test secret redaction functionality"""

    def test_detect_openai_key(self):
        """Test detecting OpenAI API key"""
        redactor = SecretRedactor()

        text = "My API key is sk-1234567890abcdefghijklmnopqrstuvwxyz123456789ABC"
        findings = redactor.detect(text)

        assert len(findings) > 0
        assert any(f[0] == 'openai_key' for f in findings)

    def test_detect_anthropic_key(self):
        """Test detecting Anthropic API key"""
        redactor = SecretRedactor()

        text = "My key: sk-ant-api03-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyzABCDEF0123456789-abcdefAA"
        findings = redactor.detect(text)

        assert len(findings) > 0
        assert any(f[0] == 'anthropic_key' for f in findings)

    def test_redact_secrets(self):
        """Test redacting secrets from text"""
        redactor = SecretRedactor()

        original = "My API key is sk-1234567890abcdefghijklmnopqrstuvwxyz123456789ABC and my password is super_secret_123"
        redacted, count = redactor.redact(original)

        assert count > 0
        assert "[REDACTED]" in redacted
        assert "sk-1234567890" not in redacted

    def test_custom_pattern(self):
        """Test adding custom redaction pattern"""
        redactor = SecretRedactor()
        redactor.add_pattern('custom_secret', r'SECRET_[A-Z0-9]{10}')

        text = "My custom secret: SECRET_ABC1234567"
        findings = redactor.detect(text)

        assert len(findings) > 0
        assert any(f[0] == 'custom_secret' for f in findings)

    def test_redaction_in_session_manager(self, temp_storage):
        """Test that SessionManager redacts when enabled"""
        manager = SessionManager(temp_storage, enable_redaction=True)

        session = manager.create_session(
            title="Test Redaction",
            provider="test",
            model="test",
            source="test"
        )

        # Commit turn with secret
        secret_key = "sk-1234567890abcdefghijklmnopqrstuvwxyz123456789ABC"
        turn = manager.commit_turn(
            session=session,
            user_message=f"Here is my key: {secret_key}",
            assistant_message="I won't share it",
            model="test",
            provider="test"
        )

        # Verify secret was redacted
        assert secret_key not in turn.user_input.content
        assert "[REDACTED]" in turn.user_input.content


class TestSearch:
    """Test search functionality"""

    def test_index_session(self, session_manager, sample_session, temp_storage):
        """Test indexing a session"""
        search_engine = SessionSearch(temp_storage)

        search_engine.index_session(session_manager, sample_session.metadata.session_id)

        # Verify index stats
        stats = search_engine.stats()
        assert stats['indexed_sessions'] >= 1
        assert stats['indexed_turns'] >= 3

    def test_search_content(self, session_manager, sample_session, temp_storage):
        """Test searching session content"""
        search_engine = SessionSearch(temp_storage)
        search_engine.index_session(session_manager, sample_session.metadata.session_id)

        # Search for content
        results = search_engine.search("User message")

        assert len(results) > 0
        assert sample_session.metadata.session_id in [r['session_id'] for r in results]

    def test_search_with_filters(self, session_manager, temp_storage):
        """Test searching with filters"""
        # Create two sessions with different providers
        session1 = session_manager.create_session(
            title="Anthropic Session",
            provider="anthropic",
            model="claude",
            source="test"
        )
        session_manager.commit_turn(
            session=session1,
            user_message="Anthropic test message",
            assistant_message="Response",
            model="claude",
            provider="anthropic"
        )

        session2 = session_manager.create_session(
            title="OpenAI Session",
            provider="openai",
            model="gpt-4",
            source="test"
        )
        session_manager.commit_turn(
            session=session2,
            user_message="OpenAI test message",
            assistant_message="Response",
            model="gpt-4",
            provider="openai"
        )

        # Index both
        search_engine = SessionSearch(temp_storage)
        search_engine.index_session(session_manager, session1.metadata.session_id)
        search_engine.index_session(session_manager, session2.metadata.session_id)

        # Search with provider filter
        results = search_engine.search("message", provider="anthropic")

        assert len(results) > 0
        assert all(r['provider'] == 'anthropic' for r in results)

    def test_rebuild_index(self, session_manager, sample_session, temp_storage):
        """Test rebuilding search index"""
        search_engine = SessionSearch(temp_storage)

        # Initial index
        search_engine.index_session(session_manager, sample_session.metadata.session_id)
        stats_before = search_engine.stats()

        # Rebuild
        search_engine.rebuild_index(session_manager)
        stats_after = search_engine.stats()

        assert stats_after['indexed_sessions'] == stats_before['indexed_sessions']
        assert stats_after['indexed_turns'] == stats_before['indexed_turns']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
