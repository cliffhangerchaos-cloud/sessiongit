"""
Pytest fixtures for SessionGit tests
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from sessiongit.core.objects import ObjectStore
from sessiongit.core.diff import FileTracker
from sessiongit.core.session_manager import SessionManager


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    temp = tempfile.mkdtemp()
    yield Path(temp)
    shutil.rmtree(temp)


@pytest.fixture
def object_store(temp_dir):
    """Create an ObjectStore instance"""
    return ObjectStore(temp_dir)


@pytest.fixture
def file_tracker(object_store):
    """Create a FileTracker instance (no working_dir - uses absolute paths)"""
    return FileTracker(object_store)


@pytest.fixture
def file_tracker_with_working_dir(object_store, temp_dir):
    """Create a FileTracker instance with working_dir set (uses relative paths)"""
    working_dir = temp_dir / "original"
    working_dir.mkdir(exist_ok=True)
    return FileTracker(object_store, working_dir=working_dir)


@pytest.fixture
def session_manager(temp_dir):
    """Create a SessionManager instance"""
    return SessionManager(temp_dir)


@pytest.fixture
def sample_text_file(temp_dir):
    """Create a sample text file"""
    file_path = temp_dir / "sample.txt"
    content = "Hello, World!\nThis is a test file.\n"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def sample_code_file(temp_dir):
    """Create a sample code file"""
    file_path = temp_dir / "auth.py"
    content = """
def authenticate(token):
    expiry = 3600  # 1 hour
    return validate_jwt(token, expiry)
""".strip()
    file_path.write_text(content)
    return file_path


@pytest.fixture
def modified_code_file(sample_code_file):
    """Modify the sample code file"""
    content = """
def authenticate(token):
    expiry = 7200  # 2 hours
    return validate_jwt(token, expiry)
""".strip()
    sample_code_file.write_text(content)
    return sample_code_file


@pytest.fixture
def sample_session_data():
    """Sample session data for testing"""
    return {
        "title": "Test Session",
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "source": "test",
    }


@pytest.fixture
def sample_turn_data():
    """Sample turn data for testing"""
    return {
        "user_message": "Help me fix the authentication bug",
        "assistant_message": "I'll help you debug the authentication issue. Let me check the code.",
        "model": "claude-sonnet-4-5",
        "provider": "anthropic",
    }
