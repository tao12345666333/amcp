"""Event converters between protocols.

This module provides functions to convert events between different protocols:
- ACP (Agent Client Protocol)
- HTTP/SSE ServerEvent
- WebSocket messages

The converters ensure consistent event representation across all protocols.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..server.models import EventType, ServerEvent, WSMessage

# ============================================================================
# ACP Event Type Mappings
# ============================================================================

# ACP session_update types to our EventType
ACP_UPDATE_TO_EVENT_TYPE: dict[str, EventType] = {
    # Message events
    "agent_message": EventType.MESSAGE_CHUNK,
    "agent_response": EventType.MESSAGE_COMPLETE,
    "agent_thought": EventType.AGENT_THINKING,
    # Tool events
    "tool_call_start": EventType.TOOL_CALL_START,
    "tool_call_update": EventType.TOOL_CALL_COMPLETE,
    # Session events
    "current_mode_update": EventType.SESSION_STATUS_CHANGED,
    "available_commands_update": EventType.SESSION_STATUS_CHANGED,
    "plan": EventType.AGENT_THINKING,
}

# Our EventType to ACP session_update types
EVENT_TYPE_TO_ACP_UPDATE: dict[EventType, str] = {
    EventType.MESSAGE_START: "agent_message",
    EventType.MESSAGE_CHUNK: "agent_message",
    EventType.MESSAGE_COMPLETE: "agent_response",
    EventType.MESSAGE_ERROR: "agent_message",
    EventType.TOOL_CALL_START: "tool_call_start",
    EventType.TOOL_CALL_COMPLETE: "tool_call_update",
    EventType.TOOL_CALL_ERROR: "tool_call_update",
    EventType.AGENT_THINKING: "agent_thought",
    EventType.AGENT_IDLE: "idle",
}


# ============================================================================
# ACP <-> ServerEvent Converters
# ============================================================================


def acp_event_to_server_event(
    acp_event: dict[str, Any],
    session_id: str | None = None,
) -> ServerEvent:
    """Convert an ACP event to a ServerEvent.

    The ACP protocol uses "session_update" types for events.
    This function maps them to our unified EventType enum.

    Args:
        acp_event: The ACP event dictionary.
        session_id: Optional session ID to include.

    Returns:
        ServerEvent with unified event type.

    Example:
        >>> acp_event = {
        ...     "session_update": "agent_message",
        ...     "content": [{"type": "text", "text": "Hello"}]
        ... }
        >>> event = acp_event_to_server_event(acp_event, "session-123")
        >>> event.type == EventType.MESSAGE_CHUNK
        True
    """
    update_type = acp_event.get("session_update", "unknown")
    event_type = ACP_UPDATE_TO_EVENT_TYPE.get(update_type, EventType.MESSAGE_CHUNK)

    # Extract content from ACP format
    payload: dict[str, Any] = {}

    if update_type in ("agent_message", "agent_response"):
        # Extract text from content blocks
        content_blocks = acp_event.get("content", [])
        text_parts = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        payload["content"] = "".join(text_parts)
        payload["done"] = update_type == "agent_response"

    elif update_type == "agent_thought":
        content_blocks = acp_event.get("content", [])
        text_parts = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        payload["thought"] = "".join(text_parts)

    elif update_type == "tool_call_start":
        payload["tool_call_id"] = acp_event.get("tool_call_id")
        payload["title"] = acp_event.get("title")
        payload["kind"] = acp_event.get("kind")

    elif update_type == "tool_call_update":
        payload["tool_call_id"] = acp_event.get("tool_call_id")
        payload["status"] = acp_event.get("status")
        # Extract content from content blocks
        content_blocks = acp_event.get("content", [])
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "content":
                inner = block.get("content", {})
                if isinstance(inner, dict) and inner.get("type") == "text":
                    payload["result"] = inner.get("text", "")
                    break

    elif update_type == "plan":
        entries = acp_event.get("entries", [])
        payload["plan"] = [
            {
                "content": e.get("content", ""),
                "priority": e.get("priority", "medium"),
                "status": e.get("status", "pending"),
            }
            for e in entries
        ]

    else:
        # Pass through unknown events
        payload = {k: v for k, v in acp_event.items() if k != "session_update"}

    return ServerEvent(
        type=event_type,
        session_id=session_id,
        timestamp=datetime.now(),
        payload=payload,
    )


def server_event_to_acp_event(event: ServerEvent) -> dict[str, Any]:
    """Convert a ServerEvent to an ACP event.

    This function creates ACP-compatible session_update messages
    from our unified ServerEvent format.

    Args:
        event: The ServerEvent to convert.

    Returns:
        ACP-compatible event dictionary.

    Example:
        >>> event = ServerEvent(
        ...     type=EventType.MESSAGE_CHUNK,
        ...     payload={"content": "Hello"}
        ... )
        >>> acp = server_event_to_acp_event(event)
        >>> acp["session_update"] == "agent_message"
        True
    """
    update_type = EVENT_TYPE_TO_ACP_UPDATE.get(event.type, "agent_message")
    result: dict[str, Any] = {"session_update": update_type}

    if event.type in (EventType.MESSAGE_START, EventType.MESSAGE_CHUNK, EventType.MESSAGE_COMPLETE):
        content = event.payload.get("content", "")
        result["content"] = [{"type": "text", "text": content}]

    elif event.type == EventType.AGENT_THINKING:
        thought = event.payload.get("thought", "")
        result["content"] = [{"type": "text", "text": thought}]

    elif event.type == EventType.TOOL_CALL_START:
        result["tool_call_id"] = event.payload.get("tool_call_id")
        result["title"] = event.payload.get("title")
        result["kind"] = event.payload.get("kind", "other")

    elif event.type in (EventType.TOOL_CALL_COMPLETE, EventType.TOOL_CALL_ERROR):
        result["tool_call_id"] = event.payload.get("tool_call_id")
        result["status"] = "completed" if event.type == EventType.TOOL_CALL_COMPLETE else "failed"
        tool_result = event.payload.get("result", "")
        result["content"] = [{"type": "content", "content": {"type": "text", "text": tool_result}}]

    elif event.type == EventType.MESSAGE_ERROR:
        error = event.payload.get("error", "Unknown error")
        result["content"] = [{"type": "text", "text": f"Error: {error}"}]

    else:
        # Pass through payload for unknown types
        result.update(event.payload)

    return result


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
