"""
SessionGit package entry point

This allows running the MCP server as a module:
    python -m sessiongit.mcp_server
"""

if __name__ == "__main__":
    from .mcp_server import main
    import asyncio
    asyncio.run(main())
