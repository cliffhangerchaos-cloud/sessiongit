"""
Diff generation and file tracking
"""

import difflib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import json


@dataclass
class FileDiff:
    """Represents changes to a file"""
    path: str
    operation: str  # 'create', 'edit', 'delete'
    hash_before: Optional[str]
    hash_after: Optional[str]
    unified_diff: Optional[str]
    lines_added: int = 0
    lines_removed: int = 0


def generate_unified_diff(
    content_before: str,
    content_after: str,
    file_path: str = "file"
) -> tuple[str, int, int]:
    """
    Generate unified diff between two text contents

    Returns:
        (unified_diff, lines_added, lines_removed)
    """
    # Don't use keepends - we add lineterm manually
    lines_before = content_before.splitlines()
    lines_after = content_after.splitlines()

    diff = difflib.unified_diff(
        lines_before,
        lines_after,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm=''
    )

    diff_lines = list(diff)
    diff_text = '\n'.join(diff_lines)

    # Count additions and deletions
    # Don't count header lines (--- and +++)
    # Only count lines that start with + or - (but not +++ or ---)
    lines_added = 0
    lines_removed = 0

    for line in diff_lines:
        if line.startswith('+') and not line.startswith('+++'):
            lines_added += 1
        elif line.startswith('-') and not line.startswith('---'):
            lines_removed += 1

    return diff_text, lines_added, lines_removed


def apply_unified_diff(content: str, diff: str) -> str:
    """
    Apply a unified diff to content

    Note: This is a simple implementation. For production,
    use a library like unidiff or patch.
    """
    # For MVP, we'll store full content instead of relying on patches
    raise NotImplementedError(
        "Diff application not needed - we store full content"
    )


class FileTracker:
    """Track file changes across turns"""

    def __init__(self, object_store, working_dir: Optional[Path] = None):
        self.object_store = object_store
        self.tracked_files = {}  # path -> current_hash
        self.working_dir = working_dir  # For relative path storage

    def _normalize_path(self, file_path: Path) -> str:
        """Convert path to relative if working_dir is set, otherwise absolute"""
        if self.working_dir:
            try:
                # Try to make it relative
                rel_path = file_path.resolve().relative_to(self.working_dir.resolve())
                return str(rel_path)
            except ValueError:
                # Path is outside working_dir, use absolute
                return str(file_path.resolve())
        return str(file_path.resolve())

    def _resolve_path(self, path_str: str) -> Path:
        """Convert stored path back to absolute Path"""
        path = Path(path_str)
        if not path.is_absolute() and self.working_dir:
            return (self.working_dir / path).resolve()
        return path.resolve()

    def track_file(self, file_path: Path) -> str:
        """
        Start tracking a file

        Returns:
            Content hash of the file
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content_hash = self.object_store.store_file(file_path)
        path_str = self._normalize_path(file_path)
        self.tracked_files[path_str] = content_hash
        return content_hash

    def detect_change(self, file_path: Path) -> Optional[FileDiff]:
        """
        Detect if a tracked file has changed

        Returns:
            FileDiff if changed, None if unchanged
        """
        path_str = self._normalize_path(file_path)

        # Not tracked yet
        if path_str not in self.tracked_files:
            if file_path.exists():
                # New file
                new_hash = self.object_store.store_file(file_path)
                self.tracked_files[path_str] = new_hash
                return FileDiff(
                    path=path_str,
                    operation='create',
                    hash_before=None,
                    hash_after=new_hash,
                    unified_diff=None,
                )
            return None

        old_hash = self.tracked_files[path_str]

        # File deleted
        if not file_path.exists():
            del self.tracked_files[path_str]
            return FileDiff(
                path=path_str,
                operation='delete',
                hash_before=old_hash,
                hash_after=None,
                unified_diff=None,
            )

        # Check if modified
        new_hash = self.object_store.hash_file(file_path)

        if new_hash == old_hash:
            # Unchanged
            return None

        # Store new version
        self.object_store.store_file(file_path)

        # Generate diff (if text file)
        diff_text = None
        lines_added = 0
        lines_removed = 0

        try:
            old_content = self.object_store.retrieve_text(old_hash)
            new_content = self.object_store.retrieve_text(new_hash)
            diff_text, lines_added, lines_removed = generate_unified_diff(
                old_content, new_content, path_str
            )
        except (UnicodeDecodeError, ValueError):
            # Binary file or not found
            pass

        self.tracked_files[path_str] = new_hash

        return FileDiff(
            path=path_str,
            operation='edit',
            hash_before=old_hash,
            hash_after=new_hash,
            unified_diff=diff_text,
            lines_added=lines_added,
            lines_removed=lines_removed,
        )

    def get_snapshot(self) -> dict[str, str]:
        """Get current snapshot of all tracked files"""
        return self.tracked_files.copy()

    def restore_snapshot(self, snapshot: dict[str, str], target_dir: Path):
        """
        Restore files from a snapshot

        Args:
            snapshot: Dict of path -> hash
            target_dir: Directory to restore into

        Raises:
            ValueError: If snapshot contains absolute paths or path traversal attempts
        """
        # Normalize target_dir to catch escapes
        target_dir = target_dir.resolve()

        for file_path_str, content_hash in snapshot.items():
            path = Path(file_path_str)

            if path.is_absolute():
                # DANGEROUS: Absolute paths would overwrite original files
                # This indicates FileTracker was created without working_dir
                raise ValueError(
                    f"Cannot restore snapshot with absolute path: {file_path_str}\n"
                    f"Snapshot was created without working_dir set.\n"
                    f"To fix: Create FileTracker with working_dir parameter."
                )

            # Relative path - join with target_dir
            dest_path = (target_dir / path).resolve()

            # Security check: prevent directory traversal (../ escapes)
            try:
                dest_path.relative_to(target_dir)
            except ValueError:
                raise ValueError(
                    f"Cannot restore file outside target directory: {file_path_str}\n"
                    f"Path would resolve to: {dest_path}\n"
                    f"Target directory: {target_dir}\n"
                    f"This may be a path traversal attempt (e.g., '../../../etc/passwd')."
                )

            self.object_store.retrieve_to_file(content_hash, dest_path)

        self.tracked_files = snapshot.copy()

    def to_dict(self) -> dict:
        """Serialize to dict"""
        return {
            'tracked_files': self.tracked_files
        }

    @classmethod
    def from_dict(cls, data: dict, object_store):
        """Deserialize from dict"""
        tracker = cls(object_store)
        tracker.tracked_files = data['tracked_files']
        return tracker
