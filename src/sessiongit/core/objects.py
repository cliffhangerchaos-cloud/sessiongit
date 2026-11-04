"""
Core VCS: Object Storage (like git objects/)

Content-addressed storage for file blobs, metadata, and snapshots.
Every object is stored by its SHA256 hash for deduplication.
"""

import hashlib
import json
import zlib
from pathlib import Path
from typing import Optional, BinaryIO
import shutil


class ObjectStore:
    """Content-addressed object storage"""

    def __init__(self, storage_path: Path):
        self.storage_path = Path(storage_path)
        self.objects_dir = self.storage_path / "objects"
        # Don't create here - let caller create explicitly during init
        # This prevents accidental directory creation on read-only operations

    def hash_content(self, content: bytes) -> str:
        """Compute SHA256 hash of content"""
        return hashlib.sha256(content).hexdigest()

    def hash_file(self, file_path: Path) -> str:
        """Compute SHA256 hash of file"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _object_path(self, content_hash: str) -> Path:
        """Get path for object (like git: objects/ab/cd123...)"""
        return self.objects_dir / content_hash[:2] / content_hash[2:]

    def exists(self, content_hash: str) -> bool:
        """Check if object exists"""
        return self._object_path(content_hash).exists()

    def store_bytes(self, content: bytes, compress: bool = True) -> str:
        """
        Store bytes and return hash

        Args:
            content: Raw bytes to store
            compress: Whether to compress (default True for text)

        Returns:
            SHA256 hash of content
        """
        content_hash = self.hash_content(content)

        # Skip if already exists (deduplication!)
        if self.exists(content_hash):
            return content_hash

        obj_path = self._object_path(content_hash)
        obj_path.parent.mkdir(parents=True, exist_ok=True)

        # Compress if requested
        data_to_write = zlib.compress(content) if compress else content

        # Write atomically (write to temp, then rename)
        temp_path = obj_path.with_suffix('.tmp')
        with open(temp_path, 'wb') as f:
            f.write(data_to_write)

        temp_path.rename(obj_path)

        # Store metadata about compression
        meta_path = obj_path.with_suffix('.meta')
        with open(meta_path, 'w') as f:
            json.dump({
                'compressed': compress,
                'size_original': len(content),
                'size_stored': len(data_to_write),
            }, f)

        return content_hash

    def store_text(self, text: str) -> str:
        """Store text content (always compressed)"""
        return self.store_bytes(text.encode('utf-8'), compress=True)

    def store_file(self, file_path: Path, compress: Optional[bool] = None) -> str:
        """
        Store file and return hash

        Args:
            file_path: Path to file
            compress: Whether to compress (auto-detect if None)

        Returns:
            SHA256 hash of file content
        """
        with open(file_path, 'rb') as f:
            content = f.read()

        # Auto-detect compression
        if compress is None:
            # Compress text files, skip binary
            try:
                content.decode('utf-8')
                compress = True
            except UnicodeDecodeError:
                compress = False

        return self.store_bytes(content, compress=compress)

    def retrieve_bytes(self, content_hash: str) -> bytes:
        """Retrieve bytes by hash"""
        if not self.exists(content_hash):
            raise ValueError(f"Object not found: {content_hash}")

        obj_path = self._object_path(content_hash)
        meta_path = obj_path.with_suffix('.meta')

        # Read metadata
        compressed = False
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
                compressed = meta.get('compressed', False)

        # Read data
        with open(obj_path, 'rb') as f:
            data = f.read()

        # Try to decompress if metadata says so
        if compressed:
            try:
                return zlib.decompress(data)
            except zlib.error:
                # Metadata says compressed but decompression failed
                # This can happen if .meta file is wrong or missing
                # Try to detect if data is actually compressed
                raise ValueError(
                    f"Object {content_hash} metadata indicates compression "
                    f"but decompression failed. Metadata may be corrupt."
                )

        # Not compressed according to metadata (or no metadata)
        # But what if it's actually compressed and .meta is missing?
        # Try to detect compression by attempting decompression
        if not meta_path.exists():
            try:
                # Attempt decompression
                decompressed = zlib.decompress(data)
                # Success! Data was compressed but .meta is missing
                # Return decompressed data
                return decompressed
            except zlib.error:
                # Not compressed, return as-is
                pass

        return data

    def retrieve_text(self, content_hash: str) -> str:
        """Retrieve text content by hash"""
        return self.retrieve_bytes(content_hash).decode('utf-8')

    def retrieve_to_file(self, content_hash: str, dest_path: Path):
        """
        Retrieve object and write to file atomically

        Writes to temp file first, then replaces destination.
        This ensures the original file is not lost if write fails.
        """
        import os
        import tempfile

        content = self.retrieve_bytes(content_hash)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first (don't delete destination yet!)
        # Use same directory as destination for atomic rename
        with tempfile.NamedTemporaryFile(
            mode='wb',
            dir=dest_path.parent,
            delete=False,
            prefix='.sessiongit_tmp_',
            suffix='_' + dest_path.name
        ) as f:
            f.write(content)
            temp_path = Path(f.name)

        # Atomic replace: overwrites destination if exists
        # os.replace() is atomic on all platforms (POSIX + Windows)
        os.replace(temp_path, dest_path)

    def get_size(self, content_hash: str) -> dict:
        """Get size information for object"""
        if not self.exists(content_hash):
            raise ValueError(f"Object not found: {content_hash}")

        obj_path = self._object_path(content_hash)
        meta_path = obj_path.with_suffix('.meta')

        if meta_path.exists():
            with open(meta_path) as f:
                return json.load(f)

        # No metadata, just return file size
        return {
            'compressed': False,
            'size_original': obj_path.stat().st_size,
            'size_stored': obj_path.stat().st_size,
        }

    def gc(self, referenced_hashes: set[str]):
        """
        Garbage collect unreferenced objects

        Args:
            referenced_hashes: Set of hashes that are still in use
        """
        removed_count = 0
        removed_bytes = 0

        # Check if objects directory exists
        if not self.objects_dir.exists():
            return {'removed_objects': 0, 'freed_bytes': 0}

        for dir_path in self.objects_dir.iterdir():
            if not dir_path.is_dir():
                continue

            for obj_path in dir_path.iterdir():
                if obj_path.suffix in {'.meta', '.tmp'}:
                    continue

                # Reconstruct full hash
                full_hash = dir_path.name + obj_path.name

                if full_hash not in referenced_hashes:
                    # Remove object and metadata
                    size = obj_path.stat().st_size
                    obj_path.unlink()
                    meta_path = obj_path.with_suffix('.meta')
                    if meta_path.exists():
                        meta_path.unlink()

                    removed_count += 1
                    removed_bytes += size

        return {'removed_objects': removed_count, 'freed_bytes': removed_bytes}

    def stats(self) -> dict:
        """Get storage statistics"""
        total_objects = 0
        total_bytes_stored = 0
        total_bytes_original = 0

        # Check if objects directory exists
        if not self.objects_dir.exists():
            return {
                'total_objects': 0,
                'bytes_stored': 0,
                'bytes_original': 0,
                'compression_ratio': 1.0,
            }

        for dir_path in self.objects_dir.iterdir():
            if not dir_path.is_dir():
                continue

            for obj_path in dir_path.iterdir():
                if obj_path.suffix in {'.meta', '.tmp'}:
                    continue

                total_objects += 1
                full_hash = dir_path.name + obj_path.name

                info = self.get_size(full_hash)
                total_bytes_stored += info['size_stored']
                total_bytes_original += info['size_original']

        return {
            'total_objects': total_objects,
            'bytes_stored': total_bytes_stored,
            'bytes_original': total_bytes_original,
            'compression_ratio': (
                total_bytes_original / total_bytes_stored
                if total_bytes_stored > 0 else 1.0
            ),
        }
