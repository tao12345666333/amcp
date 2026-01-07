"""AMCP Server - HTTP/WebSocket server for remote agent control.

This module provides a FastAPI-based server that allows:
- Remote control of AMCP agents via HTTP REST API
- Real-time streaming via WebSocket and SSE
- Multi-client session management
- Protocol-agnostic access (complements existing ACP support)

Example usage:
    # Start server
    amcp serve --port 4096

    # Connect from another terminal
    amcp attach http://localhost:4096
"""

from .app import create_app, get_app, run_server
from .config import ServerConfig, get_server_config
from .models import (
    Session,
    SessionStatus,
    PromptRequest,
    PromptResponse,
    ServerEvent,
    EventType,
    ServerInfo,
    HealthResponse,
)
from .session_manager import SessionManager, get_session_manager

__all__ = [
    # App
    "create_app",
    "get_app",
    "run_server",
    # Config
    "ServerConfig",
    "get_server_config",
    # Models
    "Session",
    "SessionStatus",
    "PromptRequest",
    "PromptResponse",
    "ServerEvent",
    "EventType",
    "ServerInfo",
    "HealthResponse",
    # Session Manager
    "SessionManager",
    "get_session_manager",
]
