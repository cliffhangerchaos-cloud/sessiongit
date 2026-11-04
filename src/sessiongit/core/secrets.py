"""
Secret redaction for SessionGit

Detects and redacts sensitive information (API keys, passwords, tokens)
before storing in sessions.
"""

import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import json


# Default patterns for common secret types
DEFAULT_PATTERNS = {
    # API Keys and Tokens
    'aws_access_key': r'AKIA[0-9A-Z]{16}',
    'aws_secret_key': r'aws_secret_access_key["\s]*[:=]["\s]*([A-Za-z0-9/+=]{40})',
    'github_token': r'gh[pousr]_[A-Za-z0-9]{36}',
    'github_classic': r'ghp_[A-Za-z0-9]{36}',
    'slack_token': r'xox[baprs]-[0-9]{10,12}-[0-9]{10,12}-[A-Za-z0-9]{24,32}',
    'slack_webhook': r'https://hooks\.slack\.com/services/T[A-Z0-9]{8}/B[A-Z0-9]{8}/[A-Za-z0-9]{24}',
    'openai_key': r'sk-[A-Za-z0-9]{48}',
    'anthropic_key': r'sk-ant-[A-Za-z0-9\-]{95,}',
    'stripe_key': r'sk_(test|live)_[0-9a-zA-Z]{24,}',
    'google_api': r'AIza[0-9A-Za-z\-_]{35}',

    # Generic patterns
    'bearer_token': r'Bearer\s+[A-Za-z0-9\-._~+/]+=*',
    'basic_auth': r'Basic\s+[A-Za-z0-9+/]+=*',
    'jwt': r'eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*',

    # Connection strings
    'connection_string': r'(mongodb|mysql|postgresql|redis)://[^\s<>"\']+',

    # Private keys (PEM format)
    'private_key': r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',

    # Generic password patterns (conservative - only obvious cases)
    'password_assignment': r'(password|passwd|pwd)["\s]*[:=]["\s]*["\'][^"\']{8,}["\']',
    'api_key_assignment': r'(api[_-]?key|apikey|access[_-]?key)["\s]*[:=]["\s]*["\'][^"\']{16,}["\']',
    'secret_assignment': r'(secret|token)["\s]*[:=]["\s]*["\'][^"\']{16,}["\']',
}


class SecretRedactor:
    """Handles detection and redaction of sensitive information"""

    def __init__(self, patterns: Optional[Dict[str, str]] = None,
                 custom_patterns_file: Optional[Path] = None):
        """
        Initialize secret redactor

        Args:
            patterns: Custom patterns (replaces defaults if provided)
            custom_patterns_file: Path to JSON file with additional patterns
        """
        # Start with default patterns
        self.patterns = DEFAULT_PATTERNS.copy() if patterns is None else patterns.copy()

        # Load custom patterns if provided
        if custom_patterns_file and custom_patterns_file.exists():
            self._load_custom_patterns(custom_patterns_file)

        # Compile regex patterns for performance
        self._compiled = {}
        invalid_patterns = []

        for name, pattern in self.patterns.items():
            try:
                self._compiled[name] = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
            except re.error as e:
                # Mark for removal
                invalid_patterns.append(name)
                print(f"Warning: Invalid regex pattern '{name}': {e}")
                print(f"Pattern will be ignored: {pattern}")

        # Remove invalid patterns
        for name in invalid_patterns:
            del self.patterns[name]

    def _load_custom_patterns(self, file_path: Path):
        """Load custom patterns from JSON file"""
        try:
            with open(file_path) as f:
                custom = json.load(f)

            # Merge with existing patterns (custom patterns take precedence)
            self.patterns.update(custom)
        except (json.JSONDecodeError, IOError) as e:
            # Don't fail - just warn
            print(f"Warning: Could not load custom patterns from {file_path}: {e}")

    def add_pattern(self, name: str, pattern: str):
        """
        Add a new pattern at runtime

        Args:
            name: Pattern name/identifier
            pattern: Regex pattern
        """
        self.patterns[name] = pattern
        self._compiled[name] = re.compile(pattern, re.IGNORECASE | re.MULTILINE)

    def remove_pattern(self, name: str):
        """Remove a pattern by name"""
        if name in self.patterns:
            del self.patterns[name]
            del self._compiled[name]

    def detect(self, text: str) -> List[Tuple[str, str, int, int]]:
        """
        Detect secrets in text

        Args:
            text: Text to scan

        Returns:
            List of (pattern_name, matched_text, start_pos, end_pos)
        """
        findings = []

        for name, compiled_pattern in self._compiled.items():
            for match in compiled_pattern.finditer(text):
                findings.append((
                    name,
                    match.group(0),
                    match.start(),
                    match.end()
                ))

        # Sort by position for consistent ordering
        findings.sort(key=lambda x: x[2])
        return findings

    def redact(self, text: str, replacement: str = "[REDACTED]") -> Tuple[str, int]:
        """
        Redact secrets in text

        Args:
            text: Text to redact
            replacement: Replacement string for secrets

        Returns:
            (redacted_text, count_of_redactions)
        """
        # Find all secrets
        findings = self.detect(text)

        if not findings:
            return text, 0

        # Build redacted text by replacing from end to start
        # (prevents position shifts)
        redacted = text
        count = 0

        for name, matched, start, end in reversed(findings):
            # For some patterns, preserve structure for debugging
            if name in ('connection_string', 'slack_webhook'):
                # Replace with pattern name for context
                replacement_text = f"[REDACTED:{name.upper()}]"
            else:
                replacement_text = replacement

            redacted = redacted[:start] + replacement_text + redacted[end:]
            count += 1

        return redacted, count

    def test(self, text: str) -> Dict:
        """
        Test redaction on sample text

        Args:
            text: Text to test

        Returns:
            Dict with findings and redacted text
        """
        findings = self.detect(text)
        redacted, count = self.redact(text)

        return {
            'original': text,
            'redacted': redacted,
            'count': count,
            'findings': [
                {
                    'pattern': name,
                    'value': matched[:50] + '...' if len(matched) > 50 else matched,
                    'position': (start, end)
                }
                for name, matched, start, end in findings
            ]
        }

    def save_patterns(self, file_path: Path):
        """Save current patterns to JSON file"""
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'w') as f:
            json.dump(self.patterns, f, indent=2)

    @classmethod
    def from_config(cls, config_path: Optional[Path] = None) -> 'SecretRedactor':
        """
        Create redactor from config file

        Args:
            config_path: Path to custom patterns file (default: ~/.sessiongit/patterns.json)

        Returns:
            SecretRedactor instance
        """
        if config_path is None:
            config_path = Path.home() / ".sessiongit" / "patterns.json"

        return cls(custom_patterns_file=config_path if config_path.exists() else None)


# Global instance
_redactor: Optional[SecretRedactor] = None


def get_redactor(config_path: Optional[Path] = None) -> SecretRedactor:
    """
    Get global redactor instance

    Args:
        config_path: Optional custom patterns file

    Returns:
        SecretRedactor instance
    """
    global _redactor

    if _redactor is None or config_path is not None:
        _redactor = SecretRedactor.from_config(config_path)

    return _redactor


def redact_text(text: str, redactor: Optional[SecretRedactor] = None) -> str:
    """
    Convenience function to redact text

    Args:
        text: Text to redact
        redactor: Optional custom redactor (uses global if None)

    Returns:
        Redacted text
    """
    if redactor is None:
        redactor = get_redactor()

    redacted, _ = redactor.redact(text)
    return redacted
