"""Event converters between protocols.

This module provides functions to convert events between different protocols:
- HTTP/SSE ServerEvent
- WebSocket messages

The converters ensure consistent event representation across all protocols.
"""

from __future__ import annotations

from typing import Any

from ..server.models import EventType, ServerEvent, WSMessage

# ============================================================================
# ServerEvent <-> WebSocket Message Converters
# ============================================================================


def server_event_to_ws_message(
    event: ServerEvent,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Convert a ServerEvent to a WebSocket message.

    The WebSocket message format follows the structure defined in the API spec.

    Args:
        event: The ServerEvent to convert.
        message_id: Optional message ID for request correlation.

    Returns:
        WebSocket message dictionary.

    Example:
        >>> event = ServerEvent(
        ...     type=EventType.MESSAGE_CHUNK,
        ...     session_id="session-123",
        ...     payload={"content": "Hello", "done": False}
        ... )
        >>> ws = server_event_to_ws_message(event, "msg-1")
        >>> ws["type"] == "event"
        True
    """
    # Determine message type
    if event.type in (EventType.MESSAGE_START, EventType.MESSAGE_CHUNK, EventType.MESSAGE_COMPLETE):
        msg_type = "response"
    elif event.type == EventType.MESSAGE_ERROR:
        msg_type = "error"
    else:
        msg_type = "event"

    # Build payload based on event type
    payload: dict[str, Any] = {
        "kind": _event_type_to_kind(event.type),
        "session_id": event.session_id,
    }

    if event.type in (EventType.MESSAGE_START, EventType.MESSAGE_CHUNK, EventType.MESSAGE_COMPLETE):
        payload["content"] = event.payload.get("content", "")
        payload["done"] = event.type == EventType.MESSAGE_COMPLETE or event.payload.get("done", False)

    elif event.type in (EventType.TOOL_CALL_START, EventType.TOOL_CALL_COMPLETE, EventType.TOOL_CALL_ERROR):
        payload["tool_name"] = event.payload.get("tool_name")
        payload["tool_call_id"] = event.payload.get("tool_call_id")
        if event.type == EventType.TOOL_CALL_START:
            payload["arguments"] = event.payload.get("arguments", {})
        else:
            payload["result"] = event.payload.get("result")
            payload["success"] = event.type == EventType.TOOL_CALL_COMPLETE

    elif event.type == EventType.MESSAGE_ERROR:
        payload["error"] = event.payload.get("error", "Unknown error")
        payload["code"] = event.payload.get("code", "INTERNAL_ERROR")

    else:
        payload.update(event.payload)

    return {
        "type": msg_type,
        "id": message_id,
        "timestamp": event.timestamp.isoformat(),
        "payload": payload,
    }


def ws_message_to_server_event(message: dict[str, Any]) -> ServerEvent | None:
    """Convert a WebSocket message to a ServerEvent.

    This is used to process incoming WebSocket messages.

    Args:
        message: The WebSocket message dictionary.

    Returns:
        ServerEvent if conversion succeeds, None otherwise.
    """
    try:
        ws_msg = WSMessage.model_validate(message)
    except Exception:
        return None

    payload = ws_msg.payload
    action = payload.get("action", payload.get("kind", "unknown"))

    # Map actions/kinds to event types
    event_type_map: dict[str, EventType] = {
        "prompt": EventType.MESSAGE_START,
        "text": EventType.MESSAGE_CHUNK,
        "complete": EventType.MESSAGE_COMPLETE,
        "tool_call": EventType.TOOL_CALL_START,
        "tool_result": EventType.TOOL_CALL_COMPLETE,
        "error": EventType.MESSAGE_ERROR,
        "cancel": EventType.SESSION_STATUS_CHANGED,
    }

    event_type = event_type_map.get(action, EventType.MESSAGE_CHUNK)

    return ServerEvent(
        type=event_type,
        session_id=payload.get("session_id"),
        timestamp=ws_msg.timestamp,
        payload=payload,
    )


# ============================================================================
# Helper Functions
# ============================================================================


def _event_type_to_kind(event_type: EventType) -> str:
    """Convert EventType to kind string for WebSocket messages."""
    kind_map = {
        EventType.CONNECTED: "connected",
        EventType.DISCONNECTED: "disconnected",
        EventType.HEARTBEAT: "heartbeat",
        EventType.SESSION_CREATED: "session_created",
        EventType.SESSION_DELETED: "session_deleted",
        EventType.SESSION_STATUS_CHANGED: "session_status",
        EventType.MESSAGE_START: "text",
        EventType.MESSAGE_CHUNK: "text",
        EventType.MESSAGE_COMPLETE: "complete",
        EventType.MESSAGE_ERROR: "error",
        EventType.TOOL_CALL_START: "tool_call",
        EventType.TOOL_CALL_COMPLETE: "tool_result",
        EventType.TOOL_CALL_ERROR: "tool_error",
        EventType.AGENT_THINKING: "thinking",
        EventType.AGENT_IDLE: "idle",
    }
    return kind_map.get(event_type, "unknown")
