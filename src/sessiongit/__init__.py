"""
SessionGit - Version Control for AI Conversations

Resume from any point. Never lose context.
"""

__version__ = "0.4.0"

from .core.session_manager import SessionManager
from .core.objects import ObjectStore
from .models.session import Session, Turn, StateBlock

__all__ = [
    "SessionManager",
    "ObjectStore",
    "Session",
    "Turn",
    "StateBlock",
]
