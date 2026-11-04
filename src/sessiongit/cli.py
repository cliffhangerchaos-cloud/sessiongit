"""
SessionGit CLI

Command-line interface for managing sessions.
"""

import click
import sys
from pathlib import Path
from datetime import datetime
from .core.session_manager import SessionManager
from .core.config import get_config, DEFAULT_CONFIG
from .core.export_import import export_session, import_session
from .core.secrets import get_redactor, SecretRedactor
from .core.search import get_search_engine
from .core.mcp_setup import (
    detect_installed_tools,
    install_to_tool,
    uninstall_from_tool,
    check_mcp_package,
    install_mcp_package,
    verify_installation,
)
from .capture.claude_desktop import ClaudeDesktopMonitor


def safe_echo(message='', **kwargs):
    """
    Echo message with proper Unicode handling for Windows console

    Falls back to ASCII representation if the console doesn't support Unicode.
    """
    try:
        click.echo(message, **kwargs)
    except UnicodeEncodeError:
        # Console doesn't support Unicode - replace unsupported chars
        encoding = sys.stdout.encoding or 'utf-8'
        safe_message = str(message).encode(encoding, errors='replace').decode(encoding)
        click.echo(safe_message, **kwargs)


def get_default_storage() -> Path:
    """Get default storage location"""
    return Path.home() / ".sessiongit"


def get_manager(ctx):
    """Get or create SessionManager"""
    if ctx.obj['manager'] is None:
        ctx.obj['manager'] = SessionManager(ctx.obj['storage'])
    return ctx.obj['manager']


def find_shortest_unique_prefixes(ids: list[str]) -> dict[str, str]:
    """
    Find the shortest unique prefix for each ID

    Returns dict mapping full ID to shortest unique prefix
    """
    result = {}

    for target_id in ids:
        # Start with the full ID length
        for length in range(1, len(target_id) + 1):
            prefix = target_id[:length]

            # Check if this prefix matches only the target
            matches = [id for id in ids if id.startswith(prefix)]

            if len(matches) == 1:
                result[target_id] = prefix
                break
        else:
            # Shouldn't happen, but fall back to full ID
            result[target_id] = target_id

    return result


@click.group()
@click.option('--storage', type=click.Path(), default=None, help='Storage directory')
@click.pass_context
def main(ctx, storage):
    """SessionGit - Version control for AI conversations"""
    if storage is None:
        storage = get_default_storage()

    ctx.ensure_object(dict)
    ctx.obj['storage'] = Path(storage)
    # Don't create manager here - let commands create it when needed
    ctx.obj['manager'] = None


@main.command()
@click.pass_context
def status(ctx):
    """Show SessionGit status"""
    storage = ctx.obj['storage']

    # Check if storage exists before creating manager
    if not storage.exists() or not (storage / "sessions").exists():
        safe_echo(f"Storage: {storage}")
        safe_echo()
        safe_echo("[ERROR] Storage not initialized")
        safe_echo("Run 'sessiongit init' to initialize storage")
        ctx.exit(1)

    manager = get_manager(ctx)

    safe_echo(f"Storage: {storage}")
    safe_echo()

    # Count sessions
    sessions = manager.list_sessions()
    active = [s for s in sessions if s.metadata.status == 'active']
    archived = [s for s in sessions if s.metadata.status == 'archived']

    safe_echo(f"[OK] Total sessions: {len(sessions)}")
    safe_echo(f"     Active: {len(active)}")
    safe_echo(f"     Archived: {len(archived)}")
    safe_echo()

    # Storage stats
    stats = manager.object_store.stats()
    safe_echo(f"Storage Stats:")
    safe_echo(f"  Objects: {stats['total_objects']}")
    safe_echo(f"  Size: {stats['bytes_stored'] / 1024:.1f} KB (original: {stats['bytes_original'] / 1024:.1f} KB)")
    safe_echo(f"  Compression: {stats['compression_ratio']:.1f}x")


@main.command()
@click.option('--limit', default=10, help='Number of sessions to show')
@click.option('--status', type=click.Choice(['active', 'archived']), help='Filter by status')
@click.pass_context
def list(ctx, limit, status):
    """List recent sessions"""
    manager = get_manager(ctx)

    # Default to active only if no status specified
    if status is None:
        sessions = [s for s in manager.list_sessions() if s.metadata.status == 'active'][:limit]
    else:
        sessions = manager.list_sessions(status=status)[:limit]

    if not sessions:
        safe_echo("No sessions found")
        return

    safe_echo(f"\n{'ID':<30} {'Title':<40} {'Turns':<8} {'Last Active':<20}")
    safe_echo("-" * 110)

    for session in sessions:
        session_id = session.metadata.session_id  # Full ID
        title = session.metadata.title[:38]
        turns = session.metadata.total_turns
        last_active = session.metadata.last_active.strftime('%Y-%m-%d %H:%M')

        safe_echo(f"{session_id:<30} {title:<40} {turns:<8} {last_active:<20}")


@main.command()
@click.argument('session_id')
@click.option('--turns', default=5, help='Number of recent turns to show')
@click.pass_context
def show(ctx, session_id, turns):
    """Show session details"""
    manager = get_manager(ctx)

    # Try exact match first, then prefix match
    session = manager.load_session(session_id, load_all_turns=True)

    if not session:
        # Try prefix matching
        all_sessions = manager.list_sessions()
        matches = [s for s in all_sessions if s.metadata.session_id.startswith(session_id)]

        if not matches:
            safe_echo(f"[ERROR] Session not found: {session_id}", err=True)
            ctx.exit(1)
        elif len(matches) > 1:
            match_ids = [s.metadata.session_id for s in matches]
            unique_prefixes = find_shortest_unique_prefixes(match_ids)

            safe_echo(f"[ERROR] Ambiguous session ID '{session_id}'. Matches:", err=True)
            for s in matches:
                full_id = s.metadata.session_id
                unique = unique_prefixes[full_id]
                safe_echo(f"  {s.metadata.title[:40]:<42}  Use: {unique}", err=True)
            ctx.exit(1)
        else:
            session = manager.load_session(matches[0].metadata.session_id, load_all_turns=True)

    # Show metadata
    meta = session.metadata
    safe_echo(f"\nSession: {meta.title}")
    safe_echo(f"ID: {meta.session_id}")
    safe_echo(f"Created: {meta.created.strftime('%Y-%m-%d %H:%M:%S')}")
    safe_echo(f"Last Active: {meta.last_active.strftime('%Y-%m-%d %H:%M:%S')}")
    safe_echo(f"Source: {meta.source} ({meta.provider}/{meta.primary_model})")
    safe_echo(f"Turns: {meta.total_turns}")
    safe_echo(f"Status: {meta.status}")

    # Show git info if available
    if session.git_repo:
        git = session.git_repo
        safe_echo(f"\nGit Repository:")
        safe_echo(f"  Path: {git.path}")
        safe_echo(f"  Branch: {git.base_branch}")
        if git.base_commit:
            safe_echo(f"  Commit: {git.base_commit[:8]}")
        else:
            safe_echo(f"  Commit: (none - empty repository)")

    # Show recent turns
    if session.turns:
        # Handle --turns 0 case: show no turns
        if turns == 0:
            turns_to_show = []
        else:
            turns_to_show = session.turns[-turns:]

        if turns_to_show:
            safe_echo(f"\nRecent Turns (last {len(turns_to_show)}):")
            for turn in turns_to_show:
                safe_echo(f"\n[Turn {turn.turn}] {turn.timestamp.strftime('%H:%M:%S')}")
                # Don't add ... if content is already short
                user_content = turn.user_input.content
                ai_content = turn.assistant_output.content
                safe_echo(f"User: {user_content if len(user_content) <= 100 else user_content[:100] + '...'}")
                safe_echo(f"AI: {ai_content if len(ai_content) <= 100 else ai_content[:100] + '...'}")

                if turn.file_operations:
                    safe_echo(f"Files: {len(turn.file_operations)} operations")

    # Show current state
    if session.current_state():
        state = session.current_state()
        safe_echo(f"\nCurrent State:")
        safe_echo(f"Goal: {state.goal}")
        if state.decisions:
            safe_echo(f"Decisions: {len(state.decisions)}")
        if state.open_questions:
            safe_echo(f"Open Questions: {len(state.open_questions)}")
        safe_echo(f"Next Step: {state.next_step}")


@main.command()
@click.argument('session_id')
@click.pass_context
def archive(ctx, session_id):
    """Archive a session"""
    manager = get_manager(ctx)

    # Check if session exists (with prefix matching)
    session = manager.load_session(session_id, load_all_turns=False)

    if not session:
        # Try prefix matching
        all_sessions = manager.list_sessions()
        matches = [s for s in all_sessions if s.metadata.session_id.startswith(session_id)]

        if not matches:
            safe_echo(f"[ERROR] Session not found: {session_id}", err=True)
            ctx.exit(1)
        elif len(matches) > 1:
            match_ids = [s.metadata.session_id for s in matches]
            unique_prefixes = find_shortest_unique_prefixes(match_ids)

            safe_echo(f"[ERROR] Ambiguous session ID '{session_id}'. Matches:", err=True)
            for s in matches:
                full_id = s.metadata.session_id
                unique = unique_prefixes[full_id]
                safe_echo(f"  {s.metadata.title[:40]:<42}  Use: {unique}", err=True)
            ctx.exit(1)
        else:
            session_id = matches[0].metadata.session_id

    manager.archive_session(session_id)
    safe_echo(f"[OK] Archived session: {session_id}")


@main.command()
@click.argument('session_id')
@click.option('--turns', default=5, help='Number of recent turns to show')
@click.option('--format', type=click.Choice(['text', 'markdown', 'json']), default='text', help='Output format')
@click.pass_context
def resume(ctx, session_id, turns, format):
    """Resume a session - show context for continuing"""
    manager = get_manager(ctx)

    # Try exact match first, then prefix match
    session = manager.load_session(session_id, load_all_turns=True)

    if not session:
        # Try prefix matching
        all_sessions = manager.list_sessions()
        matches = [s for s in all_sessions if s.metadata.session_id.startswith(session_id)]

        if not matches:
            safe_echo(f"[ERROR] Session not found: {session_id}", err=True)
            ctx.exit(1)
        elif len(matches) > 1:
            match_ids = [s.metadata.session_id for s in matches]
            unique_prefixes = find_shortest_unique_prefixes(match_ids)

            safe_echo(f"[ERROR] Ambiguous session ID '{session_id}'. Matches:", err=True)
            for s in matches:
                full_id = s.metadata.session_id
                unique = unique_prefixes[full_id]
                safe_echo(f"  {s.metadata.title[:40]:<42}  Use: {unique}", err=True)
            ctx.exit(1)
        else:
            session = manager.load_session(matches[0].metadata.session_id, load_all_turns=True)

    # Get recent turns and current state
    # Handle --turns 0 case: show no turns
    if turns == 0:
        recent_turns = []
    else:
        recent_turns = session.turns[-turns:] if session.turns else []
    current_state = session.current_state()

    if format == 'json':
        import json
        resume_data = {
            'session_id': session.metadata.session_id,
            'title': session.metadata.title,
            'total_turns': session.metadata.total_turns,
            'state': {
                'goal': current_state.goal if current_state else '',
                'decisions': current_state.decisions if current_state else [],
                'open_questions': current_state.open_questions if current_state else [],
                'next_step': current_state.next_step if current_state else '',
                'context_summary': current_state.context_summary if current_state else '',
            },
            'recent_turns': [
                {
                    'turn': t.turn,
                    'user': t.user_input.content,
                    'assistant': t.assistant_output.content,
                }
                for t in recent_turns
            ]
        }
        safe_echo(json.dumps(resume_data, indent=2, default=str))
    elif format == 'markdown':
        safe_echo(f"# Resume: {session.metadata.title}\n")
        safe_echo(f"**Session ID:** {session.metadata.session_id}")
        safe_echo(f"**Total Turns:** {session.metadata.total_turns}\n")

        if current_state:
            safe_echo(f"## Current State\n")
            safe_echo(f"**Goal:** {current_state.goal}\n")

            if current_state.decisions:
                safe_echo("**Decisions Made:**")
                for d in current_state.decisions:
                    safe_echo(f"- {d}")
                safe_echo()

            if current_state.open_questions:
                safe_echo("**Open Questions:**")
                for q in current_state.open_questions:
                    safe_echo(f"- {q}")
                safe_echo()

            safe_echo(f"**Next Step:** {current_state.next_step}\n")

        safe_echo(f"## Recent Conversation (last {len(recent_turns)} turns)\n")
        for turn in recent_turns:
            safe_echo(f"### Turn {turn.turn}")
            user_preview = turn.user_input.content[:200]
            if len(turn.user_input.content) > 200:
                user_preview += "..."
            safe_echo(f"**User:** {user_preview}")

            assistant_preview = turn.assistant_output.content[:200]
            if len(turn.assistant_output.content) > 200:
                assistant_preview += "..."
            safe_echo(f"**Assistant:** {assistant_preview}")
            safe_echo()
    else:  # text format
        safe_echo(f"\n{'='*70}")
        safe_echo(f"Resuming Session: {session.metadata.title}")
        safe_echo(f"{'='*70}\n")

        if current_state:
            safe_echo(f"Goal: {current_state.goal}\n")

            if current_state.decisions:
                safe_echo("What we've decided:")
                for d in current_state.decisions[:5]:
                    safe_echo(f"  • {d}")
                safe_echo()

            if current_state.open_questions:
                safe_echo("Still open:")
                for q in current_state.open_questions[:3]:
                    safe_echo(f"  • {q}")
                safe_echo()

            safe_echo(f"Next step: {current_state.next_step}\n")
            safe_echo(f"Context: {current_state.context_summary}\n")

        safe_echo(f"Recent conversation ({len(recent_turns)} turns shown):")
        safe_echo("-" * 70)
        for turn in recent_turns:
            safe_echo(f"\n[Turn {turn.turn}] {turn.timestamp.strftime('%Y-%m-%d %H:%M')}")
            user_preview = turn.user_input.content[:150]
            if len(turn.user_input.content) > 150:
                user_preview += "..."
            safe_echo(f"User: {user_preview}")

            ai_preview = turn.assistant_output.content[:150]
            if len(turn.assistant_output.content) > 150:
                ai_preview += "..."
            safe_echo(f"AI: {ai_preview}")


@main.command()
@click.pass_context
def monitor(ctx):
    """Start monitoring Claude Desktop (daemon mode)"""
    safe_echo("[WARNING] Auto-capture is experimental and may not work correctly.")
    safe_echo("Starting SessionGit monitor...")
    safe_echo("Watching for Claude Desktop activity...")
    safe_echo("Press Ctrl+C to stop\n")

    manager = get_manager(ctx)
    monitor = ClaudeDesktopMonitor(manager)
    monitor.start()


@main.command()
@click.pass_context
def init(ctx):
    """Initialize SessionGit storage"""
    storage = ctx.obj['storage']

    # Check if already initialized (sessions directory exists)
    if storage.exists() and (storage / "sessions").exists():
        safe_echo(f"[WARNING] Storage already initialized at: {storage}")
        ctx.exit(0)

    # Create storage structure
    storage.mkdir(parents=True, exist_ok=True)
    (storage / "sessions").mkdir(exist_ok=True)
    (storage / "objects").mkdir(exist_ok=True)

    safe_echo(f"[OK] Initialized SessionGit at: {storage}")
    safe_echo("\nNext steps:")
    safe_echo("  1. Use SessionGit via Python API (see examples/)")
    safe_echo("  2. Run 'sessiongit list' to see sessions")
    safe_echo("  3. Run 'sessiongit status' to check storage")


@main.group()
def config():
    """Manage SessionGit configuration"""
    pass


@config.command('get')
@click.argument('key')
def config_get(key):
    """Get a configuration value"""
    cfg = get_config()
    value = cfg.get(key)

    if value is None:
        safe_echo(f"[ERROR] Configuration key not found: {key}", err=True)
        safe_echo(f"Available keys: {', '.join(DEFAULT_CONFIG.keys())}", err=True)
        return

    safe_echo(f"{key} = {value}")


@config.command('set')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """Set a configuration value"""
    cfg = get_config()

    # Type conversion based on default type
    if key in DEFAULT_CONFIG:
        default = DEFAULT_CONFIG[key]

        # Convert to appropriate type
        if isinstance(default, bool):
            value = value.lower() in ('true', '1', 'yes', 'on')
        elif isinstance(default, int):
            try:
                value = int(value)
            except ValueError:
                safe_echo(f"[ERROR] Expected integer value for {key}", err=True)
                return
        elif default is None and value.lower() in ('none', 'null'):
            value = None

    cfg.set(key, value)
    cfg.save()

    safe_echo(f"[OK] Set {key} = {value}")
    safe_echo(f"Config saved to: {cfg.config_path}")


@config.command('list')
def config_list():
    """List all configuration values"""
    cfg = get_config()
    config_dict = cfg.list_all()

    safe_echo("\nSessionGit Configuration:")
    safe_echo("=" * 70)

    for key, value in sorted(config_dict.items()):
        # Show if value differs from default
        is_default = key in DEFAULT_CONFIG and DEFAULT_CONFIG[key] == value
        marker = "" if is_default else " *"
        safe_echo(f"{key:<25} = {value}{marker}")

    safe_echo()
    safe_echo("* = Modified from default")
    safe_echo(f"\nConfig file: {cfg.config_path}")


@config.command('reset')
@click.argument('key', required=False)
@click.option('--all', is_flag=True, help='Reset all configuration to defaults')
def config_reset(key, all):
    """Reset configuration to defaults"""
    cfg = get_config()

    if all:
        cfg.reset()
        cfg.save()
        safe_echo("[OK] Reset all configuration to defaults")
    elif key:
        if key not in DEFAULT_CONFIG:
            safe_echo(f"[ERROR] Unknown configuration key: {key}", err=True)
            return

        cfg.delete(key)
        cfg.save()
        safe_echo(f"[OK] Reset {key} to default: {cfg.get(key)}")
    else:
        safe_echo("[ERROR] Specify a key to reset, or use --all", err=True)


@main.command()
@click.argument('session_id')
@click.option('-o', '--output', type=click.Path(), required=True, help='Output zip file path')
@click.pass_context
def export(ctx, session_id, output):
    """Export a session to a portable zip file"""
    manager = get_manager(ctx)
    output_path = Path(output)

    # Ensure output has .zip extension
    if not output_path.suffix == '.zip':
        output_path = output_path.with_suffix('.zip')

    # Check if output file already exists
    if output_path.exists():
        safe_echo(f"[ERROR] Output file already exists: {output_path}", err=True)
        safe_echo("Remove it first or choose a different name.", err=True)
        ctx.exit(1)

    # Try exact match first, then prefix match
    session = manager.load_session(session_id, load_all_turns=False)

    if not session:
        # Try prefix matching
        all_sessions = manager.list_sessions()
        matches = [s for s in all_sessions if s.metadata.session_id.startswith(session_id)]

        if not matches:
            safe_echo(f"[ERROR] Session not found: {session_id}", err=True)
            ctx.exit(1)
        elif len(matches) > 1:
            match_ids = [s.metadata.session_id for s in matches]
            unique_prefixes = find_shortest_unique_prefixes(match_ids)

            safe_echo(f"[ERROR] Ambiguous session ID '{session_id}'. Matches:", err=True)
            for s in matches:
                full_id = s.metadata.session_id
                unique = unique_prefixes[full_id]
                safe_echo(f"  {s.metadata.title[:40]:<42}  Use: {unique}", err=True)
            ctx.exit(1)
        else:
            session_id = matches[0].metadata.session_id

    # Perform export
    try:
        safe_echo(f"Exporting session: {session_id}")
        stats = export_session(manager, session_id, output_path)

        safe_echo(f"\n[OK] Export successful!")
        safe_echo(f"Session: {stats['title']}")
        safe_echo(f"Turns: {stats['total_turns']}")
        safe_echo(f"Files: {stats['files_exported']}")
        safe_echo(f"Objects: {stats['objects_exported']}")
        safe_echo(f"Size: {stats['size_bytes'] / 1024:.1f} KB")
        safe_echo(f"\nExported to: {output_path}")

    except Exception as e:
        safe_echo(f"[ERROR] Export failed: {e}", err=True)
        # Clean up partial export
        if output_path.exists():
            output_path.unlink()
        ctx.exit(1)


@main.command(name='import')
@click.argument('import_file', type=click.Path(exists=True))
@click.option('--rename', help='Rename the imported session')
@click.pass_context
def import_cmd(ctx, import_file, rename):
    """Import a session from a zip file"""
    manager = get_manager(ctx)
    import_path = Path(import_file)

    if not import_path.suffix == '.zip':
        safe_echo(f"[ERROR] Import file must be a .zip file", err=True)
        ctx.exit(1)

    try:
        safe_echo(f"Importing session from: {import_path}")
        stats = import_session(manager, import_path, rename=rename)

        safe_echo(f"\n[OK] Import successful!")
        safe_echo(f"Session ID: {stats['session_id']}")
        safe_echo(f"Title: {stats['title']}")
        safe_echo(f"Files: {stats['files_imported']}")
        safe_echo(f"Objects: {stats['objects_imported']}")
        safe_echo(f"\nUse 'sessiongit show {stats['session_id'][:12]}' to view")

    except ValueError as e:
        safe_echo(f"[ERROR] Import failed: {e}", err=True)
        ctx.exit(1)
    except Exception as e:
        safe_echo(f"[ERROR] Unexpected error during import: {e}", err=True)
        ctx.exit(1)


@main.group()
def secrets():
    """Manage secret redaction patterns"""
    pass


@secrets.command('test')
@click.option('--text', help='Text to test (or use stdin)')
def secrets_test(text):
    """Test secret redaction on sample text"""
    redactor = get_redactor()

    # Read from stdin if no text provided
    if text is None:
        safe_echo("Enter text to test (Ctrl+D or Ctrl+Z to finish):")
        text = sys.stdin.read()

    # Perform test
    result = redactor.test(text)

    safe_echo("\n=== Original ===")
    safe_echo(result['original'])

    safe_echo("\n=== Redacted ===")
    safe_echo(result['redacted'])

    if result['findings']:
        safe_echo(f"\n=== Found {result['count']} Secret(s) ===")
        for finding in result['findings']:
            safe_echo(f"  Pattern: {finding['pattern']}")
            safe_echo(f"  Value: {finding['value']}")
            safe_echo(f"  Position: {finding['position']}")
            safe_echo()
    else:
        safe_echo("\n[OK] No secrets detected")


@secrets.command('list-patterns')
@click.option('--verbose', is_flag=True, help='Show full regex patterns')
def secrets_list_patterns(verbose):
    """List all redaction patterns"""
    redactor = get_redactor()

    safe_echo("\nSecret Redaction Patterns:")
    safe_echo("=" * 70)

    for name, pattern in sorted(redactor.patterns.items()):
        safe_echo(f"\n{name}")
        if verbose:
            safe_echo(f"  Regex: {pattern}")
        else:
            # Show short description based on name
            safe_echo(f"  Type: {name.replace('_', ' ').title()}")

    safe_echo(f"\nTotal patterns: {len(redactor.patterns)}")

    # Show if custom patterns file exists
    patterns_file = Path.home() / ".sessiongit" / "patterns.json"
    if patterns_file.exists():
        safe_echo(f"Custom patterns file: {patterns_file}")


@secrets.command('add-pattern')
@click.argument('name')
@click.argument('pattern')
def secrets_add_pattern(name, pattern):
    """Add a custom redaction pattern"""
    import re

    # Validate regex pattern first
    try:
        re.compile(pattern)
    except re.error as e:
        safe_echo(f"[ERROR] Invalid regex pattern: {e}", err=True)
        safe_echo(f"Pattern: {pattern}", err=True)
        return

    patterns_file = Path.home() / ".sessiongit" / "patterns.json"

    # Load existing custom patterns or create new dict
    if patterns_file.exists():
        import json
        with open(patterns_file) as f:
            custom_patterns = json.load(f)
    else:
        custom_patterns = {}

    # Add new pattern
    custom_patterns[name] = pattern

    # Save
    patterns_file.parent.mkdir(parents=True, exist_ok=True)
    import json
    with open(patterns_file, 'w') as f:
        json.dump(custom_patterns, f, indent=2)

    safe_echo(f"[OK] Added pattern '{name}'")
    safe_echo(f"Pattern: {pattern}")
    safe_echo(f"\nSaved to: {patterns_file}")
    safe_echo("\nNote: Restart SessionGit or create a new session for changes to take effect")


@secrets.command('remove-pattern')
@click.argument('name')
def secrets_remove_pattern(name):
    """Remove a custom redaction pattern"""
    patterns_file = Path.home() / ".sessiongit" / "patterns.json"

    if not patterns_file.exists():
        safe_echo("[ERROR] No custom patterns file found", err=True)
        return

    # Load custom patterns
    import json
    with open(patterns_file) as f:
        custom_patterns = json.load(f)

    if name not in custom_patterns:
        safe_echo(f"[ERROR] Pattern '{name}' not found in custom patterns", err=True)
        safe_echo(f"Available patterns: {', '.join(custom_patterns.keys())}", err=True)
        return

    # Remove pattern
    del custom_patterns[name]

    # Save
    with open(patterns_file, 'w') as f:
        json.dump(custom_patterns, f, indent=2)

    safe_echo(f"[OK] Removed pattern '{name}'")


@main.command()
@click.argument('query')
@click.option('--status', type=click.Choice(['active', 'archived']), help='Filter by status')
@click.option('--after', help='Only sessions created after this date (YYYY-MM-DD)')
@click.option('--before', help='Only sessions created before this date (YYYY-MM-DD)')
@click.option('--provider', help='Filter by provider')
@click.option('--model', help='Filter by model')
@click.option('--limit', default=20, help='Maximum results to return')
@click.option('--reindex', is_flag=True, help='Reindex before searching')
@click.pass_context
def search(ctx, query, status, after, before, provider, model, limit, reindex):
    """Search across all sessions"""
    storage = ctx.obj['storage']

    # Check if storage exists
    if not storage.exists():
        safe_echo(f"[ERROR] Storage not initialized at: {storage}", err=True)
        safe_echo("Run 'sessiongit init' first", err=True)
        ctx.exit(1)

    manager = get_manager(ctx)
    search_engine = get_search_engine(storage)

    # Reindex if requested
    if reindex:
        safe_echo("Reindexing all sessions...")
        search_engine.rebuild_index(manager)
        safe_echo("[OK] Reindex complete\n")

    # Parse dates if provided
    after_date = None
    before_date = None

    if after:
        try:
            after_date = datetime.strptime(after, '%Y-%m-%d')
        except ValueError:
            safe_echo(f"[ERROR] Invalid date format for --after: {after}", err=True)
            safe_echo("Use YYYY-MM-DD format", err=True)
            ctx.exit(1)

    if before:
        try:
            before_date = datetime.strptime(before, '%Y-%m-%d')
        except ValueError:
            safe_echo(f"[ERROR] Invalid date format for --before: {before}", err=True)
            safe_echo("Use YYYY-MM-DD format", err=True)
            ctx.exit(1)

    # Perform search
    try:
        results = search_engine.search(
            query=query,
            status=status,
            after_date=after_date,
            before_date=before_date,
            provider=provider,
            model=model,
            limit=limit
        )
    except ValueError as e:
        safe_echo(f"[ERROR] {e}", err=True)
        safe_echo("\nSearch syntax tips:", err=True)
        safe_echo("  - Simple: 'authentication'", err=True)
        safe_echo("  - AND: 'auth AND token'", err=True)
        safe_echo("  - OR: 'auth OR token'", err=True)
        safe_echo("  - Phrase: '\"exact phrase\"'", err=True)
        safe_echo("  - NOT: 'auth NOT test'", err=True)
        ctx.exit(1)

    if not results:
        safe_echo(f"No results found for: {query}")
        safe_echo("\nTip: Use 'sessiongit search --reindex' to rebuild the search index")
        return

    # Display results
    safe_echo(f"\nFound {len(results)} result(s) for: {query}")
    safe_echo("=" * 100)

    for i, result in enumerate(results, 1):
        safe_echo(f"\n[{i}] {result['title']}")
        safe_echo(f"    Session: {result['session_id']}")
        safe_echo(f"    Turn: {result['turn_number']}/{result['total_turns']}")
        safe_echo(f"    Date: {result['timestamp'][:19]}")
        safe_echo(f"    Status: {result['status']}")

        # Show snippet with highlighted matches
        snippet = result['snippet'].replace('[MATCH]', '>>> ').replace('[/MATCH]', ' <<<')
        safe_echo(f"\n    {snippet}")

    safe_echo("\n" + "=" * 100)
    safe_echo(f"\nUse 'sessiongit show <session-id>' to view full session")


@main.group()
def index():
    """Manage search index"""
    pass


@index.command('rebuild')
@click.pass_context
def index_rebuild(ctx):
    """Rebuild the entire search index"""
    storage = ctx.obj['storage']
    manager = get_manager(ctx)
    search_engine = get_search_engine(storage)

    safe_echo("Rebuilding search index...")
    safe_echo("This may take a while for large repositories...\n")

    search_engine.rebuild_index(manager)

    stats = search_engine.stats()
    safe_echo("[OK] Index rebuilt successfully!")
    safe_echo(f"\nIndexed sessions: {stats['indexed_sessions']}")
    safe_echo(f"Indexed turns: {stats['indexed_turns']}")
    safe_echo(f"Database size: {stats['database_size_bytes'] / 1024:.1f} KB")


@index.command('stats')
@click.pass_context
def index_stats(ctx):
    """Show search index statistics"""
    storage = ctx.obj['storage']
    search_engine = get_search_engine(storage)

    stats = search_engine.stats()

    safe_echo("\nSearch Index Statistics:")
    safe_echo("=" * 50)
    safe_echo(f"Indexed sessions: {stats['indexed_sessions']}")
    safe_echo(f"Indexed turns: {stats['indexed_turns']}")
    safe_echo(f"Database size: {stats['database_size_bytes'] / 1024:.1f} KB")


@index.command('update')
@click.pass_context
def index_update(ctx):
    """Update search index with new sessions/turns"""
    storage = ctx.obj['storage']
    manager = get_manager(ctx)
    search_engine = get_search_engine(storage)

    safe_echo("Updating search index...")

    search_engine.index_all_sessions(manager)

    safe_echo("[OK] Index updated!")


@main.command()
@click.option('--tool', help='Specific tool to configure (claude, cursor, continue, windsurf)')
@click.option('--list', 'list_tools', is_flag=True, help='List detected tools')
@click.option('--uninstall', is_flag=True, help='Remove SessionGit from tools')
@click.option('--force', is_flag=True, help='Overwrite existing configuration')
def setup(tool, list_tools, uninstall, force):
    """Setup SessionGit MCP server for AI tools (Claude Desktop, Cursor, etc.)"""

    safe_echo("🔧 SessionGit MCP Setup\n")

    # Step 1: Check mcp package
    safe_echo("Step 1: Checking dependencies...")
    if not check_mcp_package():
        safe_echo("  ⚠️  MCP package not found")
        safe_echo("  Installing mcp package...")

        if install_mcp_package():
            safe_echo("  ✅ MCP package installed")
        else:
            safe_echo("  ❌ Failed to install mcp package", err=True)
            safe_echo("\nPlease install manually:", err=True)
            safe_echo("  pip install mcp", err=True)
            return
    else:
        safe_echo("  ✅ MCP package installed")

    # Step 2: Detect tools
    safe_echo("\nStep 2: Detecting AI tools...")
    detected = detect_installed_tools()

    if not detected:
        safe_echo("  ⚠️  No compatible AI tools detected")
        safe_echo("\n  Supported tools:")
        safe_echo("    - Claude Desktop")
        safe_echo("    - Cursor")
        safe_echo("    - Continue")
        safe_echo("    - Windsurf")
        safe_echo("\n  Install one of these tools and run setup again.")
        return

    # List mode
    if list_tools:
        safe_echo(f"\n  Found {len(detected)} tool(s):")
        for mcp_tool, config_path in detected:
            safe_echo(f"    • {mcp_tool.display_name}")
            safe_echo(f"      Config: {config_path}")
            success, msg = verify_installation(mcp_tool, config_path)
            if success:
                safe_echo(f"      Status: ✅ {msg}")
            else:
                safe_echo(f"      Status: ⚠️  {msg}")
        return

    # Filter by specific tool if requested
    if tool:
        detected = [(t, p) for t, p in detected if t.name == tool.lower()]
        if not detected:
            safe_echo(f"  ❌ Tool '{tool}' not found", err=True)
            return

    safe_echo(f"  Found {len(detected)} tool(s):")
    for mcp_tool, _ in detected:
        safe_echo(f"    • {mcp_tool.display_name}")

    # Step 3: Install or uninstall
    if uninstall:
        safe_echo("\nStep 3: Removing SessionGit...")
        for mcp_tool, config_path in detected:
            if uninstall_from_tool(mcp_tool, config_path):
                safe_echo(f"  ✅ Removed from {mcp_tool.display_name}")
            else:
                safe_echo(f"  ⚠️  Not configured in {mcp_tool.display_name}")

        safe_echo("\n✅ Uninstall complete!")
        safe_echo("Restart your AI tools for changes to take effect.")
        return

    # Install mode
    safe_echo("\nStep 3: Configuring tools...")
    configured = []
    skipped = []
    failed = []

    for mcp_tool, config_path in detected:
        try:
            if install_to_tool(mcp_tool, config_path, force=force):
                configured.append(mcp_tool.display_name)
                safe_echo(f"  ✅ Configured {mcp_tool.display_name}")
                if config_path.with_suffix('.json.backup').exists():
                    safe_echo(f"     (backup saved: {config_path.with_suffix('.json.backup')})")
            else:
                skipped.append(mcp_tool.display_name)
                safe_echo(f"  ⚠️  {mcp_tool.display_name} already configured (use --force to overwrite)")
        except Exception as e:
            failed.append(mcp_tool.display_name)
            safe_echo(f"  ❌ Failed to configure {mcp_tool.display_name}: {e}", err=True)

    # Summary
    safe_echo("\n" + "=" * 60)
    safe_echo("📊 Setup Summary:")
    if configured:
        safe_echo(f"  ✅ Configured: {', '.join(configured)}")
    if skipped:
        safe_echo(f"  ⚠️  Skipped: {', '.join(skipped)}")
    if failed:
        safe_echo(f"  ❌ Failed: {', '.join(failed)}")

    # Step 4: Next steps
    if configured:
        safe_echo("\n" + "=" * 60)
        safe_echo("🚀 Next Steps:")
        safe_echo("  1. Restart your AI tool(s)")
        safe_echo("  2. Try: \"List my SessionGit sessions\"")
        safe_echo("  3. Documentation: MCP_SERVER_SETUP.md")
        safe_echo("\n✅ Setup complete!")
    elif skipped and not failed:
        safe_echo("\n✅ Already set up! Restart your AI tools to use SessionGit.")
    else:
        safe_echo("\n⚠️  Setup incomplete. Check errors above.")


if __name__ == '__main__':
    main()
