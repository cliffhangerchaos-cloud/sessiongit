"""
Configuration management for SessionGit
"""

import json
from pathlib import Path
from typing import Any, Optional


DEFAULT_CONFIG = {
    'storage_path': str(Path.home() / ".sessiongit"),
    'snapshot_frequency': 10,  # Create snapshot every N turns
    'compression': True,  # Enable compression for objects
    'auto_archive_days': None,  # Auto-archive after N days (None = disabled)
    'default_list_limit': 10,  # Default number of sessions to show in list
    'editor': None,  # Editor for editing turns (None = $EDITOR)
    'enable_redaction': False,  # Automatically redact secrets before storage
}


class Config:
    """Manage SessionGit configuration"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration

        Args:
            config_path: Path to config file (default: ~/.sessiongitrc)
        """
        if config_path is None:
            config_path = Path.home() / ".sessiongitrc"

        self.config_path = Path(config_path)
        self._config = DEFAULT_CONFIG.copy()

        # Load config if exists
        if self.config_path.exists():
            self.load()

    def load(self):
        """Load configuration from file"""
        try:
            with open(self.config_path) as f:
                user_config = json.load(f)

            # Merge with defaults (user config takes precedence)
            self._config.update(user_config)
        except (json.JSONDecodeError, IOError) as e:
            # If config is corrupted, start fresh
            print(f"Warning: Could not load config: {e}")
            self._config = DEFAULT_CONFIG.copy()

    def save(self):
        """Save configuration to file"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_path, 'w') as f:
            json.dump(self._config, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value

        Args:
            key: Configuration key
            default: Default value if key doesn't exist

        Returns:
            Configuration value or default
        """
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        """
        Set configuration value

        Args:
            key: Configuration key
            value: New value
        """
        self._config[key] = value

    def delete(self, key: str):
        """
        Delete configuration key (revert to default)

        Args:
            key: Configuration key to delete
        """
        if key in self._config and key in DEFAULT_CONFIG:
            self._config[key] = DEFAULT_CONFIG[key]
        elif key in self._config:
            del self._config[key]

    def list_all(self) -> dict:
        """Get all configuration values"""
        return self._config.copy()

    def reset(self):
        """Reset all configuration to defaults"""
        self._config = DEFAULT_CONFIG.copy()

    @property
    def storage_path(self) -> Path:
        """Get storage path as Path object"""
        return Path(self.get('storage_path'))

    @property
    def snapshot_frequency(self) -> int:
        """Get snapshot frequency"""
        return int(self.get('snapshot_frequency', 10))

    @property
    def compression_enabled(self) -> bool:
        """Check if compression is enabled"""
        return bool(self.get('compression', True))

    @property
    def auto_archive_days(self) -> Optional[int]:
        """Get auto-archive days (None if disabled)"""
        value = self.get('auto_archive_days')
        return int(value) if value is not None else None

    @property
    def default_list_limit(self) -> int:
        """Get default list limit"""
        return int(self.get('default_list_limit', 10))


# Global config instance
_config = None


def get_config(config_path: Optional[Path] = None) -> Config:
    """
    Get global configuration instance

    Args:
        config_path: Optional custom config path

    Returns:
        Config instance
    """
    global _config

    if _config is None or config_path is not None:
        _config = Config(config_path)

    return _config
