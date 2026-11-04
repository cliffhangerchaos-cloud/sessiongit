"""
Unit tests for FileTracker
"""

import pytest
from pathlib import Path


@pytest.mark.unit
class TestFileTracker:
    """Test FileTracker functionality"""

    def test_track_file(self, file_tracker, sample_text_file):
        """Test tracking a new file"""
        content_hash = file_tracker.track_file(sample_text_file)

        assert content_hash is not None
        assert len(content_hash) == 64  # SHA256 hash
        # Normalize path for comparison (handles Windows short/long paths)
        normalized_path = str(sample_text_file.resolve())
        assert normalized_path in file_tracker.tracked_files or str(sample_text_file) in file_tracker.tracked_files

    def test_track_nonexistent_file(self, file_tracker, temp_dir):
        """Test tracking a file that doesn't exist"""
        nonexistent = temp_dir / "nonexistent.txt"

        with pytest.raises(FileNotFoundError):
            file_tracker.track_file(nonexistent)

    def test_detect_no_change(self, file_tracker, sample_text_file):
        """Test detecting no change in tracked file"""
        # Track file
        file_tracker.track_file(sample_text_file)

        # Check again (no change)
        diff = file_tracker.detect_change(sample_text_file)
        assert diff is None

    def test_detect_new_file(self, file_tracker, temp_dir):
        """Test detecting a new file"""
        # Create a new file
        new_file = temp_dir / "new.txt"
        new_file.write_text("New content")

        # Detect should return create operation
        diff = file_tracker.detect_change(new_file)

        assert diff is not None
        assert diff.operation == 'create'
        assert diff.hash_before is None
        assert diff.hash_after is not None
        # Path might be normalized/resolved - check both forms
        assert diff.path == str(new_file) or diff.path == str(new_file.resolve())

    def test_detect_edit(self, file_tracker, sample_code_file):
        """Test detecting file edit"""
        # Track original file
        file_tracker.track_file(sample_code_file)

        # Modify file
        modified_content = """
def authenticate(token):
    expiry = 7200  # 2 hours - CHANGED
    return validate_jwt(token, expiry)
""".strip()
        sample_code_file.write_text(modified_content)

        # Detect change
        diff = file_tracker.detect_change(sample_code_file)

        assert diff is not None
        assert diff.operation == 'edit'
        assert diff.hash_before is not None
        assert diff.hash_after is not None
        assert diff.hash_before != diff.hash_after
        assert diff.unified_diff is not None
        assert diff.lines_added > 0 or diff.lines_removed > 0

    def test_detect_delete(self, file_tracker, sample_text_file):
        """Test detecting file deletion"""
        # Track file
        file_tracker.track_file(sample_text_file)

        # Delete file
        sample_text_file.unlink()

        # Detect deletion
        diff = file_tracker.detect_change(sample_text_file)

        assert diff is not None
        assert diff.operation == 'delete'
        assert diff.hash_before is not None
        assert diff.hash_after is None

    def test_unified_diff_generation(self, file_tracker, sample_code_file):
        """Test that unified diff is generated correctly"""
        # Track original
        original_content = sample_code_file.read_text()
        file_tracker.track_file(sample_code_file)

        # Modify
        modified_content = original_content.replace("3600", "7200")
        sample_code_file.write_text(modified_content)

        # Detect
        diff = file_tracker.detect_change(sample_code_file)

        assert diff.unified_diff is not None
        assert "3600" in diff.unified_diff or "7200" in diff.unified_diff
        assert "++" in diff.unified_diff or "--" in diff.unified_diff

    def test_get_snapshot(self, file_tracker, temp_dir):
        """Test getting workspace snapshot"""
        # Create and track multiple files
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"

        file1.write_text("Content 1")
        file2.write_text("Content 2")

        hash1 = file_tracker.track_file(file1)
        hash2 = file_tracker.track_file(file2)

        # Get snapshot
        snapshot = file_tracker.get_snapshot()

        assert len(snapshot) == 2
        # FileTracker normalizes paths - get the normalized versions
        tracked_paths = list(snapshot.keys())
        assert len(tracked_paths) == 2
        # Verify hashes are present
        assert hash1 in snapshot.values()
        assert hash2 in snapshot.values()

    def test_restore_snapshot(self, file_tracker_with_working_dir, temp_dir, object_store):
        """Test restoring from snapshot"""
        # Use the working_dir from the fixture
        file_tracker = file_tracker_with_working_dir
        working_dir = file_tracker.working_dir

        # Create files in the working directory
        file1 = working_dir / "file1.txt"
        file1.write_text("Original content 1")

        file2 = working_dir / "file2.txt"
        file2.write_text("Original content 2")

        # Track and get snapshot
        file_tracker.track_file(file1)
        file_tracker.track_file(file2)
        snapshot = file_tracker.get_snapshot()

        # Restore to new directory
        restore_dir = temp_dir / "restored"
        restore_dir.mkdir()

        file_tracker.restore_snapshot(snapshot, restore_dir)

        # Verify files restored
        restored1 = restore_dir / file1.name
        restored2 = restore_dir / file2.name

        assert restored1.exists()
        assert restored2.exists()
        assert restored1.read_text() == "Original content 1"
        assert restored2.read_text() == "Original content 2"

    def test_binary_file_detection(self, file_tracker, temp_dir):
        """Test that binary files are handled (no diff generated)"""
        # Create binary file
        binary_file = temp_dir / "binary.dat"
        binary_file.write_bytes(bytes(range(256)))

        # Track
        file_tracker.track_file(binary_file)

        # Modify - use valid byte range (0-255)
        # Create a different 256-byte pattern
        binary_file.write_bytes(bytes([(i + 100) % 256 for i in range(256)]))

        # Detect
        diff = file_tracker.detect_change(binary_file)

        assert diff is not None
        assert diff.operation == 'edit'
        assert diff.unified_diff is None  # No diff for binary files

    def test_serialization(self, file_tracker, sample_text_file):
        """Test to_dict and from_dict"""
        # Track a file
        file_tracker.track_file(sample_text_file)

        # Serialize
        data = file_tracker.to_dict()
        assert 'tracked_files' in data
        # Path is normalized in tracked_files
        assert len(data['tracked_files']) == 1

        # Deserialize
        from sessiongit.core.diff import FileTracker
        restored = FileTracker.from_dict(data, file_tracker.object_store)

        assert restored.tracked_files == file_tracker.tracked_files
