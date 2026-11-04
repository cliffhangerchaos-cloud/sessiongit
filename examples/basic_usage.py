"""
SessionGit Basic Usage Example

This example shows how to use SessionGit programmatically.
"""

from pathlib import Path
from sessiongit import SessionManager
from sessiongit.models.session import StateBlock, FileOperation
from datetime import datetime

# Initialize SessionManager
storage = Path.home() / ".sessiongit"
manager = SessionManager(storage)

print("SessionGit Example\n")

# ===== CREATE A SESSION =====
print("1. Creating a new session...")

session = manager.create_session(
    title="Example coding session",
    provider="anthropic",
    model="claude-sonnet-4-5",
    source="api",
    working_dir=Path.cwd(),
)

print(f"   ✓ Created session: {session.metadata.session_id}")
print(f"   Title: {session.metadata.title}")
print()

# ===== COMMIT FIRST TURN =====
print("2. Committing first turn...")

state = StateBlock(
    goal="Learn how to use SessionGit",
    next_step="Commit a turn with file operations",
    context_summary="User is learning SessionGit API",
    decisions=["Use SessionManager for session management"],
)

turn1 = manager.commit_turn(
    session=session,
    user_message="How do I use SessionGit?",
    assistant_message="SessionGit is a version control system for AI conversations. Let me show you...",
    model="claude-sonnet-4-5",
    provider="anthropic",
    state=state,
)

print(f"   ✓ Committed turn {turn1.turn}")
print()

# ===== COMMIT TURN WITH FILE OPERATION =====
print("3. Committing turn with file operation...")

# Simulate reading a file
file_op = FileOperation(
    type="file_read",
    path="/example/auth.py",
    timestamp=datetime.now(),
    hash_before=manager.object_store.hash_content(b"example content"),
)

state.next_step = "Implement authentication"
state.decisions.append("Read auth.py to understand current implementation")

turn2 = manager.commit_turn(
    session=session,
    user_message="Show me the authentication code",
    assistant_message="Here's the current auth code... I see you're using JWT.",
    model="claude-sonnet-4-5",
    provider="anthropic",
    file_operations=[file_op],
    state=state,
)

print(f"   ✓ Committed turn {turn2.turn} with file operation")
print()

# ===== LIST SESSIONS =====
print("4. Listing all sessions...")

sessions = manager.list_sessions()
print(f"   Found {len(sessions)} sessions:")

for s in sessions[:5]:
    print(f"   - {s.metadata.title} ({s.metadata.total_turns} turns)")
print()

# ===== LOAD SESSION =====
print("5. Loading session back...")

loaded = manager.load_session(session.metadata.session_id, load_all_turns=True)
print(f"   ✓ Loaded session: {loaded.metadata.title}")
print(f"   Turns: {loaded.metadata.total_turns}")
print()

# ===== SHOW SESSION STATE =====
print("6. Current session state:")

current_state = loaded.current_state()
if current_state:
    print(f"   Goal: {current_state.goal}")
    print(f"   Decisions: {len(current_state.decisions)}")
    for decision in current_state.decisions:
        print(f"     - {decision}")
    print(f"   Next Step: {current_state.next_step}")
print()

# ===== SHOW RECENT TURNS =====
print("7. Recent conversation:")

for turn in loaded.turns:
    print(f"\n   [Turn {turn.turn}]")
    print(f"   User: {turn.user_input.content[:60]}...")
    print(f"   AI: {turn.assistant_output.content[:60]}...")
    if turn.file_operations:
        print(f"   Files: {len(turn.file_operations)} operations")
print()

# ===== ARCHIVE SESSION =====
print("8. Archiving session...")

manager.archive_session(session.metadata.session_id)
print("   ✓ Session archived")
print()

# ===== STORAGE STATS =====
print("9. Storage statistics:")

stats = manager.object_store.stats()
print(f"   Objects stored: {stats['total_objects']}")
print(f"   Bytes stored: {stats['bytes_stored']:,}")
print(f"   Bytes original: {stats['bytes_original']:,}")
print(f"   Compression ratio: {stats['compression_ratio']:.1f}x")
print()

print("✅ Example complete!")
print()
print("Next steps:")
print("  - Run: sessiongit list")
print("  - Try: sessiongit show", session.metadata.session_id[:18])
