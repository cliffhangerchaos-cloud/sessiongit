"""
Unit tests for ObjectStore
"""

import pytest
from pathlib import Path


@pytest.mark.unit
class TestObjectStore:
    """Test ObjectStore functionality"""

    def test_init_does_not_create_objects_dir(self, temp_dir):
        """Test that ObjectStore does not create objects directory on init"""
        from sessiongit.core.objects import ObjectStore

        store = ObjectStore(temp_dir)
        # v0.1.1: directories are created on first write, not on construction
        assert not (temp_dir / "objects").exists()

        # But it should be created when storing content
        store.store_text("test content")
        assert (temp_dir / "objects").exists()
        assert (temp_dir / "objects").is_dir()

    def test_hash_content(self, object_store):
        """Test content hashing"""
        content = b"Hello, World!"
        hash1 = object_store.hash_content(content)
        hash2 = object_store.hash_content(content)

        # Same content = same hash
        assert hash1 == hash2

        # Different content = different hash
        hash3 = object_store.hash_content(b"Different content")
        assert hash1 != hash3

        # Hash should be 64 chars (SHA256)
        assert len(hash1) == 64

    def test_store_and_retrieve_bytes(self, object_store):
        """Test storing and retrieving bytes"""
        content = b"Test content"

        # Store
        content_hash = object_store.store_bytes(content, compress=False)

        # Verify stored
        assert object_store.exists(content_hash)

        # Retrieve
        retrieved = object_store.retrieve_bytes(content_hash)
        assert retrieved == content

    def test_store_and_retrieve_text(self, object_store):
        """Test storing and retrieving text"""
        text = "Hello, World!\nThis is a test."

        # Store
        content_hash = object_store.store_text(text)

        # Retrieve
        retrieved = object_store.retrieve_text(content_hash)
        assert retrieved == text

    def test_store_file(self, object_store, sample_text_file):
        """Test storing a file"""
        # Store file
        content_hash = object_store.store_file(sample_text_file)

        # Verify stored
        assert object_store.exists(content_hash)

        # Retrieve and verify content matches
        # Read as bytes and decode to match what object store does
        # This handles CRLF/LF differences on Windows
        retrieved = object_store.retrieve_text(content_hash)
        original = sample_text_file.read_bytes().decode('utf-8')
        assert retrieved == original

    def test_compression(self, object_store):
        """Test that compression works"""
        # Large repeating text (very compressible)
        text = "Hello World! " * 1000

        # Store with compression
        hash_compressed = object_store.store_text(text)
        size_info = object_store.get_size(hash_compressed)

        # Should be compressed
        assert size_info['compressed']
        assert size_info['size_stored'] < size_info['size_original']

    def test_deduplication(self, object_store):
        """Test that duplicate content is deduplicated"""
        content = b"Duplicate content"

        # Store same content twice
        hash1 = object_store.store_bytes(content)
        hash2 = object_store.store_bytes(content)

        # Should have same hash
        assert hash1 == hash2

        # Should only be stored once
        obj_path = object_store._object_path(hash1)
        assert obj_path.exists()

    def test_retrieve_to_file(self, object_store, temp_dir):
        """Test retrieving object to file"""
        content = b"Test content for file"

        # Store
        content_hash = object_store.store_bytes(content)

        # Retrieve to file
        dest_file = temp_dir / "retrieved.txt"
        object_store.retrieve_to_file(content_hash, dest_file)

        # Verify file exists and content matches
        assert dest_file.exists()
        assert dest_file.read_bytes() == content

    def test_get_size(self, object_store):
        """Test getting size information"""
        content = b"Test content"

        content_hash = object_store.store_bytes(content, compress=False)
        size_info = object_store.get_size(content_hash)

        assert size_info['size_original'] == len(content)
        assert size_info['size_stored'] == len(content)
        assert not size_info['compressed']

    def test_stats(self, object_store):
        """Test storage statistics"""
        # Store some files
        object_store.store_bytes(b"Content 1")
        object_store.store_bytes(b"Content 2")
        object_store.store_bytes(b"Content 3")

        stats = object_store.stats()

        assert stats['total_objects'] == 3
        assert stats['bytes_stored'] > 0
        assert stats['bytes_original'] > 0
        assert stats['compression_ratio'] > 0

    def test_object_not_found(self, object_store):
        """Test retrieving non-existent object"""
        with pytest.raises(ValueError, match="Object not found"):
            object_store.retrieve_bytes("nonexistent_hash")

    def test_binary_file(self, object_store, temp_dir):
        """Test storing binary file"""
        # Create a binary file
        binary_file = temp_dir / "binary.dat"
        binary_content = bytes(range(256))
        binary_file.write_bytes(binary_content)

        # Store
        content_hash = object_store.store_file(binary_file)

        # Retrieve
        retrieved = object_store.retrieve_bytes(content_hash)
        assert retrieved == binary_content

    def test_large_file(self, object_store, temp_dir):
        """Test storing large file (with compression)"""
        # Create a large text file (1MB of repeating text)
        large_file = temp_dir / "large.txt"
        content = "Hello World! " * 100000  # ~1MB
        large_file.write_text(content)

        # Store with compression
        content_hash = object_store.store_file(large_file, compress=True)

        # Verify compression worked
        size_info = object_store.get_size(content_hash)
        assert size_info['compressed']
        assert size_info['size_stored'] < size_info['size_original']

        # Verify retrieval works
        retrieved = object_store.retrieve_text(content_hash)
        assert retrieved == content
