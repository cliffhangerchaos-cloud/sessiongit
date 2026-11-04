"""
Export and import sessions as portable bundles
"""

import json
import zipfile
from pathlib import Path
from typing import Optional
import shutil
import os


def _is_safe_path(base_path: Path, target_path: Path) -> bool:
    """
    Check if target_path is safely within base_path (no path traversal)

    Args:
        base_path: The base directory
        target_path: The target path to validate

    Returns:
        True if safe, False if path traversal detected
    """
    # Resolve to absolute paths
    base = base_path.resolve()
    target = target_path.resolve()

    # Check if target is within base
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def export_session(session_manager, session_id: str, output_path: Path) -> dict:
    """
    Export a session to a portable zip file

    Args:
        session_manager: SessionManager instance
        session_id: Session ID to export
        output_path: Path to output zip file

    Returns:
        Dict with export statistics

    Raises:
        ValueError: If session not found
    """
    # Load session (metadata only for verification)
    session = session_manager.load_session(session_id, load_all_turns=False)

    if not session:
        raise ValueError(f"Session not found: {session_id}")

    # Paths
    session_dir = session_manager.sessions_dir / session_id
    objects_dir = session_manager.object_store.objects_dir

    # Statistics
    stats = {
        'session_id': session_id,
        'title': session.metadata.title,
        'total_turns': session.metadata.total_turns,
        'files_exported': 0,
        'objects_exported': 0,
        'size_bytes': 0,
    }

    # Create zip file
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Export session directory (meta.json, turns/, snapshots/)
        for file_path in session_dir.rglob('*'):
            if file_path.is_file():
                arcname = f"session/{file_path.relative_to(session_dir)}"
                zipf.write(file_path, arcname)
                stats['files_exported'] += 1

        # Collect all referenced objects from turns
        referenced_objects = set()

        # Load all turns to find object hashes
        full_session = session_manager.load_session(session_id, load_all_turns=True)
        for turn in full_session.turns:
            # File operations contain hashes
            for file_op in turn.file_operations:
                if file_op.hash_before:
                    referenced_objects.add(file_op.hash_before)
                if file_op.hash_after:
                    referenced_objects.add(file_op.hash_after)

            # Workspace snapshot contains hashes
            for hash_value in turn.workspace_snapshot.values():
                referenced_objects.add(hash_value)

        # Export referenced objects
        for obj_hash in referenced_objects:
            obj_path = session_manager.object_store._object_path(obj_hash)
            meta_path = obj_path.with_suffix('.meta')

            if obj_path.exists():
                # Add object file
                arcname = f"objects/{obj_hash[:2]}/{obj_hash[2:]}"
                zipf.write(obj_path, arcname)
                stats['objects_exported'] += 1

                # Add metadata file if exists
                if meta_path.exists():
                    arcname_meta = f"objects/{obj_hash[:2]}/{obj_hash[2:]}.meta"
                    zipf.write(meta_path, arcname_meta)

        # Add export metadata
        export_metadata = {
            'version': '1.0',
            'session_id': session_id,
            'exported_at': session.metadata.last_active.isoformat(),
            'metadata': {
                'title': session.metadata.title,
                'created': session.metadata.created.isoformat(),
                'total_turns': session.metadata.total_turns,
                'provider': session.metadata.provider,
                'model': session.metadata.primary_model,
            }
        }

        zipf.writestr('export.json', json.dumps(export_metadata, indent=2))

    stats['size_bytes'] = output_path.stat().st_size

    return stats


def import_session(session_manager, import_path: Path, rename: Optional[str] = None) -> dict:
    """
    Import a session from a zip file

    Args:
        session_manager: SessionManager instance
        import_path: Path to zip file to import
        rename: Optional new title for imported session

    Returns:
        Dict with import statistics

    Raises:
        ValueError: If zip is invalid or session already exists
    """
    if not import_path.exists():
        raise ValueError(f"Import file not found: {import_path}")

    # Extract and validate export metadata
    with zipfile.ZipFile(import_path, 'r') as zipf:
        # Read export metadata
        try:
            export_json = zipf.read('export.json').decode('utf-8')
            export_metadata = json.loads(export_json)
        except KeyError:
            raise ValueError("Invalid export file: missing export.json")

        session_id = export_metadata['session_id']

        # Check if session already exists
        if session_manager.load_session(session_id, load_all_turns=False):
            raise ValueError(f"Session already exists: {session_id}")

        # Statistics
        stats = {
            'session_id': session_id,
            'title': export_metadata['metadata']['title'],
            'files_imported': 0,
            'objects_imported': 0,
        }

        # Extract session files
        session_dir = session_manager.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        for member in zipf.namelist():
            if member.startswith('session/'):
                # Extract to session directory
                target_path = session_dir / member[8:]  # Remove 'session/' prefix

                # Validate path (prevent path traversal)
                if not _is_safe_path(session_dir, target_path):
                    raise ValueError(f"Security error: Path traversal detected in zip entry: {member}")

                target_path.parent.mkdir(parents=True, exist_ok=True)

                with zipf.open(member) as source:
                    with open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)

                stats['files_imported'] += 1

            elif member.startswith('objects/'):
                # Extract to objects directory
                # member format: objects/ab/cd123...
                hash_part = member[8:]  # Remove 'objects/' prefix
                target_path = session_manager.object_store.objects_dir / hash_part

                # Validate path (prevent path traversal)
                if not _is_safe_path(session_manager.object_store.objects_dir, target_path):
                    raise ValueError(f"Security error: Path traversal detected in zip entry: {member}")

                target_path.parent.mkdir(parents=True, exist_ok=True)

                with zipf.open(member) as source:
                    with open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)

                if not member.endswith('.meta'):
                    stats['objects_imported'] += 1

        # Rename if requested
        if rename:
            meta_file = session_dir / "meta.json"
            with open(meta_file) as f:
                meta_data = json.load(f)

            meta_data['metadata']['title'] = rename

            with open(meta_file, 'w') as f:
                json.dump(meta_data, f, indent=2, default=str)

            stats['title'] = rename

    return stats
