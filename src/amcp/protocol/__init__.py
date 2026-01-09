"""Protocol unification module for AMCP.

This module provides adapters and converters between different protocols:
- ACP (Agent Client Protocol)
- HTTP REST API
- WebSocket

The goal is to ensure consistent behavior and error handling across all protocols.
"""

from __future__ import annotations

from .adapter import ProtocolAdapter, get_protocol_adapter
from .converters import (
    acp_event_to_server_event,
    server_event_to_acp_event,
    server_event_to_ws_message,
    ws_message_to_server_event,
)
from .error_codes import ErrorCode, ProtocolError

__all__ = [
    "ProtocolAdapter",
    "get_protocol_adapter",
    "ErrorCode",
    "ProtocolError",
    "acp_event_to_server_event",
    "server_event_to_acp_event",
    "server_event_to_ws_message",
    "ws_message_to_server_event",
]
