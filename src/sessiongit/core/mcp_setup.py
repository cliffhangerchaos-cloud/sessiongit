"""
Universal MCP Setup Utilities

Auto-detects and configures MCP-compatible AI tools.
Supports: Claude Desktop, Cursor, and other MCP-compatible tools.
"""

import json
import platform
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Tuple


class MCPTool:
    """Configuration for an MCP-compatible tool"""

    def __init__(self, name: str, display_name: str, config_paths: List[Path],
                 config_key: str = "mcpServers", test_command: Optional[str] = None):
        self.name = name
        self.display_name = display_name
        self.config_paths = config_paths
        self.config_key = config_key
        self.test_command = test_command

    def find_config(self) -> Optional[Path]:
        """Find the config file for this tool"""
        for path in self.config_paths:
            if path.exists():
                return path
        return None

    def is_installed(self) -> bool:
        """Check if this tool is installed"""
        # Check if config directory exists
        for path in self.config_paths:
            if path.parent.exists():
                return True

        # Try test command if provided
        if self.test_command:
            try:
                subprocess.run(
                    self.test_command.split(),
                    capture_output=True,
                    timeout=2
                )
                return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return False


def get_supported_tools() -> List[MCPTool]:
    """Get list of supported MCP-compatible tools with their config paths"""
    system = platform.system()
    home = Path.home()

    tools = []

    # Claude Desktop
    if system == "Windows":
        claude_paths = [
            Path(home) / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
        ]
    elif system == "Darwin":  # macOS
        claude_paths = [
            Path(home) / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        ]
    else:  # Linux
        claude_paths = [
            Path(home) / ".config" / "Claude" / "claude_desktop_config.json"
        ]

    tools.append(MCPTool(
        name="claude",
        display_name="Claude Desktop",
        config_paths=claude_paths,
        config_key="mcpServers"
    ))

    # Cursor
    if system == "Windows":
        cursor_paths = [
            Path(home) / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage" / "mcp.json",
            Path(home) / ".cursor" / "mcp.json",
        ]
    elif system == "Darwin":  # macOS
        cursor_paths = [
            Path(home) / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "mcp.json",
            Path(home) / ".cursor" / "mcp.json",
        ]
    else:  # Linux
        cursor_paths = [
            Path(home) / ".config" / "Cursor" / "User" / "globalStorage" / "mcp.json",
            Path(home) / ".cursor" / "mcp.json",
        ]

    tools.append(MCPTool(
        name="cursor",
        display_name="Cursor",
        config_paths=cursor_paths,
        config_key="mcpServers"
    ))

    # Continue (similar to Cursor)
    if system == "Windows":
        continue_paths = [
            Path(home) / "AppData" / "Roaming" / "Continue" / "config.json",
            Path(home) / ".continue" / "config.json",
        ]
    elif system == "Darwin":
        continue_paths = [
            Path(home) / "Library" / "Application Support" / "Continue" / "config.json",
            Path(home) / ".continue" / "config.json",
        ]
    else:
        continue_paths = [
            Path(home) / ".config" / "Continue" / "config.json",
            Path(home) / ".continue" / "config.json",
        ]

    tools.append(MCPTool(
        name="continue",
        display_name="Continue",
        config_paths=continue_paths,
        config_key="mcpServers"
    ))

    # Windsurf
    if system == "Windows":
        windsurf_paths = [
            Path(home) / "AppData" / "Roaming" / "Windsurf" / "mcp.json",
        ]
    elif system == "Darwin":
        windsurf_paths = [
            Path(home) / "Library" / "Application Support" / "Windsurf" / "mcp.json",
        ]
    else:
        windsurf_paths = [
            Path(home) / ".config" / "Windsurf" / "mcp.json",
        ]

    tools.append(MCPTool(
        name="windsurf",
        display_name="Windsurf",
        config_paths=windsurf_paths,
        config_key="mcpServers"
    ))

    return tools


def detect_installed_tools() -> List[Tuple[MCPTool, Path]]:
    """
    Detect which MCP-compatible tools are installed

    Returns:
        List of (tool, config_path) tuples for installed tools
    """
    installed = []

    for tool in get_supported_tools():
        config_path = tool.find_config()
        if config_path:
            installed.append((tool, config_path))
        elif tool.is_installed():
            # Tool is installed but no config yet - use first config path
            installed.append((tool, tool.config_paths[0]))

    return installed


def get_sessiongit_config() -> Dict:
    """Get the SessionGit MCP server configuration"""
    import sys

    # Get python executable path
    python_path = sys.executable

    return {
        "sessiongit": {
            "command": python_path,
            "args": ["-m", "sessiongit.mcp_server"],
            "env": {
                "PYTHONUNBUFFERED": "1"
            }
        }
    }


def read_config(config_path: Path) -> Dict:
    """Read existing config file, return empty dict if doesn't exist"""
    if not config_path.exists():
        return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def write_config(config_path: Path, config: Dict, backup: bool = True):
    """Write config file, optionally backing up existing one"""
    # Create backup if requested and file exists
    if backup and config_path.exists():
        backup_path = config_path.with_suffix('.json.backup')
        import shutil
        shutil.copy2(config_path, backup_path)

    # Ensure parent directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write config
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)


def install_to_tool(tool: MCPTool, config_path: Path, force: bool = False) -> bool:
    """
    Install SessionGit MCP server to a tool's config

    Args:
        tool: MCPTool instance
        config_path: Path to config file
        force: Overwrite existing SessionGit config if present

    Returns:
        True if installed, False if already present and not forced
    """
    # Read existing config
    config = read_config(config_path)

    # Ensure mcpServers key exists
    if tool.config_key not in config:
        config[tool.config_key] = {}

    # Check if already installed
    if "sessiongit" in config[tool.config_key] and not force:
        return False

    # Add SessionGit config
    sessiongit_config = get_sessiongit_config()
    config[tool.config_key].update(sessiongit_config)

    # Write config (with backup)
    write_config(config_path, config, backup=True)

    return True


def uninstall_from_tool(tool: MCPTool, config_path: Path) -> bool:
    """
    Remove SessionGit from a tool's config

    Returns:
        True if removed, False if wasn't present
    """
    if not config_path.exists():
        return False

    config = read_config(config_path)

    if tool.config_key not in config:
        return False

    if "sessiongit" not in config[tool.config_key]:
        return False

    # Remove SessionGit
    del config[tool.config_key]["sessiongit"]

    # Write updated config
    write_config(config_path, config, backup=True)

    return True


def check_mcp_package() -> bool:
    """Check if mcp package is installed"""
    try:
        import mcp
        return True
    except ImportError:
        return False


def install_mcp_package() -> bool:
    """Install mcp package"""
    import subprocess
    import sys

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "mcp", "--break-system-packages"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError:
        # Try without --break-system-packages
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "mcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except subprocess.CalledProcessError:
            return False


def verify_installation(tool: MCPTool, config_path: Path) -> Tuple[bool, str]:
    """
    Verify SessionGit is properly configured for a tool

    Returns:
        (success: bool, message: str)
    """
    if not config_path.exists():
        return False, "Config file not found"

    config = read_config(config_path)

    if tool.config_key not in config:
        return False, f"'{tool.config_key}' key not found in config"

    if "sessiongit" not in config[tool.config_key]:
        return False, "SessionGit not configured"

    sessiongit_config = config[tool.config_key]["sessiongit"]

    if "command" not in sessiongit_config:
        return False, "Missing 'command' in SessionGit config"

    if "args" not in sessiongit_config:
        return False, "Missing 'args' in SessionGit config"

    return True, "Configured correctly"
