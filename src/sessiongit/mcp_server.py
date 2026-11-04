"""
SessionGit MCP Server

Provides MCP tools for AI assistants to track, search, and resume conversations.

This is a properly implemented MCP server using the official mcp package.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, EmbeddedResource

from .core.session_manager import SessionManager
from .core.search import get_search_engine
from .core.export_import import export_session, import_session
from .core.config import get_config
from .models.session import StateBlock


def get_default_storage() -> Path:
    """Get default storage path from config"""
    config = get_config()
    return Path(config.get('storage_path', Path.home() / ".sessiongit"))


# Global session manager (initialized on first use)
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get or create global session manager"""
    global _session_manager
    if _session_manager is None:
        storage_path = get_default_storage()
        _session_manager = SessionManager(storage_path)
    return _session_manager


def resolve_session_id(session_id_or_prefix: str, manager: SessionManager) -> Optional[str]:
    """
    Resolve a session ID or prefix to a full session ID

    Args:
        session_id_or_prefix: Full session ID or unique prefix
        manager: SessionManager instance

    Returns:
        Full session ID if found and unique, None otherwise
    """
    # Try exact match first
    session = manager.load_session(session_id_or_prefix, load_all_turns=False)
    if session:
        return session_id_or_prefix

    # Try prefix matching
    all_sessions = manager.list_sessions()
    matches = [s for s in all_sessions if s.metadata.session_id.startswith(session_id_or_prefix)]

    if len(matches) == 1:
        return matches[0].metadata.session_id
    elif len(matches) > 1:
        # Ambiguous - return None (caller will handle error)
        return None
    else:
        # Not found
        return None


# Create MCP server
app = Server("sessiongit")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available SessionGit MCP tools"""
    return [
        Tool(
            name="sessiongit_create",
            description="Create a new SessionGit session to track a conversation",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title/description of this session (e.g., 'Debugging JWT auth')",
                    },
                    "provider": {
                        "type": "string",
                        "description": "AI provider (e.g., 'anthropic', 'openai')",
                        "default": "anthropic",
                    },
                    "model": {
                        "type": "string",
                        "description": "Model name (e.g., 'claude-sonnet-4-5')",
                        "default": "claude-sonnet-4-5",
                    },
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="sessiongit_commit_turn",
            description="Save a turn (user message + AI response) to a session",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to commit to",
                    },
                    "user_message": {
                        "type": "string",
                        "description": "User's message/prompt",
                    },
                    "assistant_message": {
                        "type": "string",
                        "description": "AI assistant's response",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Current goal/objective (optional)",
                    },
                    "next_step": {
                        "type": "string",
                        "description": "Next planned step (optional)",
                    },
                },
                "required": ["session_id", "user_message", "assistant_message"],
            },
        ),
        Tool(
            name="sessiongit_list",
            description="List saved sessions with metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "number",
                        "description": "Maximum sessions to return",
                        "default": 10,
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status: 'active' or 'archived'",
                        "enum": ["active", "archived"],
                    },
                },
            },
        ),
        Tool(
            name="sessiongit_search",
            description="Search across all session content (messages, goals, decisions)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (supports AND, OR, NOT, phrases)",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status",
                        "enum": ["active", "archived"],
                    },
                    "limit": {
                        "type": "number",
                        "description": "Maximum results",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="sessiongit_resume",
            description="Resume a session - get full context to continue from where you left off",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to resume (use sessiongit_search to find)",
                    },
                    "recent_turns": {
                        "type": "number",
                        "description": "Number of recent turns to include",
                        "default": 5,
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="sessiongit_export",
            description="Export a session as a portable zip file",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to export",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Path to save zip file",
                    },
                },
                "required": ["session_id", "output_path"],
            },
        ),
        Tool(
            name="sessiongit_import",
            description="Import a session from a zip file",
            inputSchema={
                "type": "object",
                "properties": {
                    "import_path": {
                        "type": "string",
                        "description": "Path to zip file to import",
                    },
                    "rename": {
                        "type": "string",
                        "description": "Optional new title for imported session",
                    },
                },
                "required": ["import_path"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls"""
    manager = get_session_manager()

    try:
        if name == "sessiongit_create":
            # Create new session
            session = manager.create_session(
                title=arguments["title"],
                provider=arguments.get("provider", "anthropic"),
                model=arguments.get("model", "claude-sonnet-4-5"),
                source="mcp",
            )

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "session_id": session.metadata.session_id,
                        "title": session.metadata.title,
                        "message": f"Created session: {session.metadata.session_id}",
                    }, indent=2),
                )
            ]

        elif name == "sessiongit_commit_turn":
            # Commit a turn
            # Resolve session ID (supports prefixes)
            session_id = resolve_session_id(arguments["session_id"], manager)
            if not session_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": "Session not found or ambiguous prefix"})
                )]

            session = manager.load_session(session_id)
            if not session:
                return [TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": "Session not found"})
                )]

            # Build state block if goal/next_step provided
            state = None
            if arguments.get("goal") or arguments.get("next_step"):
                state = StateBlock(
                    goal=arguments.get("goal", ""),
                    next_step=arguments.get("next_step", ""),
                    context_summary="",
                )

            turn = manager.commit_turn(
                session=session,
                user_message=arguments["user_message"],
                assistant_message=arguments["assistant_message"],
                model=session.metadata.primary_model,
                provider=session.metadata.provider,
                state=state,
            )

            # Update search index with new turn
            storage = get_default_storage()
            try:
                search_engine = get_search_engine(storage)
                search_engine.index_session(manager, session.metadata.session_id, incremental=True)
            except Exception:
                # If indexing fails, don't break the commit
                pass

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "session_id": session.metadata.session_id,
                        "turn": turn.turn,
                        "message": f"Committed turn {turn.turn}",
                    }, indent=2),
                )
            ]

        elif name == "sessiongit_list":
            # List sessions
            limit = arguments.get("limit", 10)
            status_filter = arguments.get("status")

            sessions = manager.list_sessions(status=status_filter)[:limit]

            results = [
                {
                    "session_id": s.metadata.session_id,
                    "title": s.metadata.title,
                    "created": s.metadata.created.isoformat(),
                    "last_active": s.metadata.last_active.isoformat(),
                    "turns": s.metadata.total_turns,
                    "status": s.metadata.status,
                    "provider": s.metadata.provider,
                    "model": s.metadata.primary_model,
                }
                for s in sessions
            ]

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "count": len(results),
                        "sessions": results,
                    }, indent=2),
                )
            ]

        elif name == "sessiongit_search":
            # Search sessions
            storage = get_default_storage()
            search_engine = get_search_engine(storage)

            # Ensure index exists
            if not (storage / "search.db").exists():
                # Build index first
                search_engine.index_all_sessions(manager)

            query = arguments["query"]
            status_filter = arguments.get("status")
            limit = arguments.get("limit", 10)

            results = search_engine.search(
                query=query,
                status=status_filter,
                limit=limit
            )

            formatted_results = [
                {
                    "session_id": r["session_id"],
                    "title": r["title"],
                    "turn": r["turn_number"],
                    "snippet": r["snippet"],
                    "timestamp": r["timestamp"],
                    "status": r["status"],
                }
                for r in results
            ]

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "query": query,
                        "count": len(formatted_results),
                        "results": formatted_results,
                    }, indent=2),
                )
            ]

        elif name == "sessiongit_resume":
            # Resume session
            # Resolve session ID (supports prefixes)
            session_id = resolve_session_id(arguments["session_id"], manager)
            if not session_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": "Session not found or ambiguous prefix"})
                )]

            recent_turns_count = arguments.get("recent_turns", 5)

            session = manager.load_session(session_id, load_all_turns=True)
            if not session:
                return [TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": "Session not found"})
                )]

            # Get recent turns (handle 0 case explicitly)
            if recent_turns_count == 0:
                recent_turns = []
            elif session.turns:
                recent_turns = session.turns[-recent_turns_count:]
            else:
                recent_turns = []
            current_state = session.current_state()

            resume_data = {
                "success": True,
                "session_id": session.metadata.session_id,
                "title": session.metadata.title,
                "total_turns": session.metadata.total_turns,
                "created": session.metadata.created.isoformat(),
                "last_active": session.metadata.last_active.isoformat(),
                "state": {
                    "goal": current_state.goal if current_state else "",
                    "next_step": current_state.next_step if current_state else "",
                    "context": current_state.context_summary if current_state else "",
                    "decisions": current_state.decisions if current_state else [],
                    "open_questions": current_state.open_questions if current_state else [],
                },
                "recent_turns": [
                    {
                        "turn": t.turn,
                        "timestamp": t.timestamp.isoformat(),
                        "user": t.user_input.content,
                        "assistant": t.assistant_output.content,
                    }
                    for t in recent_turns
                ],
            }

            return [
                TextContent(
                    type="text",
                    text=json.dumps(resume_data, indent=2),
                )
            ]

        elif name == "sessiongit_export":
            # Export session
            # Resolve session ID (supports prefixes)
            session_id = resolve_session_id(arguments["session_id"], manager)
            if not session_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": "Session not found or ambiguous prefix"})
                )]

            output_path = Path(arguments["output_path"])

            stats = export_session(manager, session_id, output_path)

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "session_id": stats["session_id"],
                        "title": stats["title"],
                        "output_path": str(output_path),
                        "size_kb": round(stats["size_bytes"] / 1024, 1),
                        "files": stats["files_exported"],
                        "objects": stats["objects_exported"],
                    }, indent=2),
                )
            ]

        elif name == "sessiongit_import":
            # Import session
            import_path = Path(arguments["import_path"])
            rename = arguments.get("rename")

            stats = import_session(manager, import_path, rename=rename)

            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "session_id": stats["session_id"],
                        "title": stats["title"],
                        "files": stats["files_imported"],
                        "objects": stats["objects_imported"],
                    }, indent=2),
                )
            ]

        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": f"Unknown tool: {name}"})
                )
            ]

    except Exception as e:
        return [
            TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                }, indent=2)
            )
        ]


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
