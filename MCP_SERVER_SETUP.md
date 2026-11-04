# MCP Server Setup (Claude Desktop)

**Note:** This is an **optional integration** for Claude Desktop users. SessionGit works with any AI tool via the Python API - MCP just enables automatic tracking in Claude Desktop.

How to hook SessionGit into Claude Desktop so it can automatically track your conversations.

## What You Get

Once set up, Claude Desktop can:
- Create sessions automatically when you start working
- Save conversation turns with file content
- Search through your past sessions
- Resume old conversations with full context
- Export/import sessions

Basically Claude becomes aware of SessionGit and can use it naturally.

## Requirements

- Claude Desktop installed
- SessionGit installed (`pip install -e .`)
- MCP package installed (`pip install mcp`)

## Setup

### 1. Install Everything

```bash
cd sessiongit
pip install -e .
pip install mcp
```

### 2. Find Your Claude Config

**Windows:**
`%APPDATA%\Claude\claude_desktop_config.json`

**macOS:**
`~/Library/Application Support/Claude/claude_desktop_config.json`

**Linux:**
`~/.config/Claude/claude_desktop_config.json`

If the file doesn't exist, create it.

### 3. Add SessionGit to Config

Open the config file and add this:

```json
{
  "mcpServers": {
    "sessiongit": {
      "command": "python",
      "args": ["-m", "sessiongit.mcp_server"]
    }
  }
}
```

If you already have other MCP servers configured, just add sessiongit to the mcpServers object.

### 4. Restart Claude Desktop

Completely quit and restart Claude Desktop. The MCP connection initializes on startup.

## Testing It Works

Open Claude Desktop and try:

```
You: List my SessionGit sessions
Claude: [should show your sessions or say there are none yet]

You: Create a SessionGit session for this conversation
Claude: [creates a session]

You: Search for "auth bug"
Claude: [searches your sessions]
```

If Claude can't find the tools, check the developer console:
- Windows: `Ctrl+Shift+I`
- macOS: `Cmd+Option+I`

Look for MCP connection errors.

## Troubleshooting

**"python: No module named sessiongit"**

SessionGit isn't in your Python path. Make sure you ran `pip install -e .` from the sessiongit directory.

**MCP server won't connect**

Check your python path in the config. If you use a virtual environment, you need the full path:

```json
{
  "mcpServers": {
    "sessiongit": {
      "command": "/full/path/to/venv/bin/python",
      "args": ["-m", "sessiongit.mcp_server"]
    }
  }
}
```

**Works but Claude doesn't use it**

You need to explicitly tell Claude to use SessionGit. It won't automatically create sessions. Say things like "create a SessionGit session" or "search my sessions for X".

**How do I see what tools are available?**

In Claude Desktop, open the developer console and look for MCP initialization logs. You should see sessiongit listed with tools like sessiongit_create, sessiongit_commit_turn, sessiongit_list, etc.

## Available Tools

Once configured, Claude has access to:

- `sessiongit_create` - Create new sessions
- `sessiongit_commit_turn` - Save conversation turns
- `sessiongit_list` - List all sessions
- `sessiongit_search` - Search across sessions
- `sessiongit_resume` - Load a session with full context
- `sessiongit_export` - Export a session to zip
- `sessiongit_import` - Import a session from zip

## Usage Examples

**Creating a session:**
```
You: Let's create a SessionGit session to track this debugging work
Claude: [creates session with ID sess_20261104_abc123]
```

**Committing turns manually:**
```
You: Save this conversation to the session
Claude: [commits the current turn]
```

**Searching:**
```
You: What sessions do I have about JWT auth?
Claude: [searches and lists matching sessions]
```

**Resuming:**
```
You: Load the session from yesterday about the login bug
Claude: [searches for it, loads with full context]
```

## Configuration

SessionGit uses your standard config at `~/.sessiongitrc`. The MCP server respects:
- `storage_path` - Where sessions are stored
- `enable_redaction` - Auto-redact secrets
- `compression` - File compression settings

Change these with `sessiongit config set key value`.

## Notes

- Sessions are stored locally, not synced to Claude's servers
- The MCP server runs as a subprocess of Claude Desktop
- Each restart of Claude Desktop creates a fresh MCP connection
- If SessionGit updates, restart Claude Desktop to pick up changes

## Uninstalling

Remove the sessiongit entry from `claude_desktop_config.json` and restart Claude Desktop.
