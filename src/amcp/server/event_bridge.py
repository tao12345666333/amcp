"""Event integration for AMCP Server.

Integrates the server's event system with:
- Tool execution events
- Agent thinking events
- Session status changes

This module bridges the Agent's internal events with the
WebSocket/SSE event system for real-time client notifications.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .events import get_event_emitter
from .models import EventType, ServerEvent
from .websocket import get_connection_manager


class EventBridge:
    """Bridges internal agent events to server event system.

    Subscribes to agent events and broadcasts them to connected clients
    via WebSocket and SSE.
    """

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}
        self._running = False

    async def emit_tool_call_start(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        """Emit a tool call start event.

        Args:
            session_id: The session ID.
            tool_name: Name of the tool being called.
            arguments: Tool arguments.
        """
        event = ServerEvent(
            type=EventType.TOOL_CALL_START,
            session_id=session_id,
            payload={
                "tool_name": tool_name,
                "arguments": arguments,
            },
        )
        await self._broadcast_event(session_id, event)

    async def emit_tool_call_complete(
        self,
        session_id: str,
        tool_name: str,
        result: str,
        success: bool = True,
        duration_ms: float | None = None,
    ) -> None:
        """Emit a tool call complete event.

        Args:
            session_id: The session ID.
            tool_name: Name of the tool.
            result: Tool execution result.
            success: Whether the tool call succeeded.
            duration_ms: Optional execution duration in milliseconds.
        """
        event = ServerEvent(
            type=EventType.TOOL_CALL_COMPLETE if success else EventType.TOOL_CALL_ERROR,
            session_id=session_id,
            payload={
                "tool_name": tool_name,
                "result": result[:500] if len(result) > 500 else result,  # Truncate long results
                "success": success,
                "duration_ms": duration_ms,
            },
        )
        await self._broadcast_event(session_id, event)

    async def emit_agent_thinking(
        self,
        session_id: str,
        content: str | None = None,
    ) -> None:
        """Emit an agent thinking event.

        Args:
            session_id: The session ID.
            content: Optional thinking content.
        """
        event = ServerEvent(
            type=EventType.AGENT_THINKING,
            session_id=session_id,
            payload={"content": content} if content else {},
        )
        await self._broadcast_event(session_id, event)

    async def emit_agent_idle(self, session_id: str) -> None:
        """Emit an agent idle event.

        Args:
            session_id: The session ID.
        """
        event = ServerEvent(
            type=EventType.AGENT_IDLE,
            session_id=session_id,
            payload={},
        )
        await self._broadcast_event(session_id, event)

    async def emit_message_chunk(
        self,
        session_id: str,
        content: str,
        message_id: str | None = None,
    ) -> None:
        """Emit a message chunk event (streaming).

        Args:
            session_id: The session ID.
            content: The chunk content.
            message_id: Optional message ID.
        """
        event = ServerEvent(
            type=EventType.MESSAGE_CHUNK,
            session_id=session_id,
            payload={
                "content": content,
                "message_id": message_id,
            },
        )
        await self._broadcast_event(session_id, event)

    async def emit_session_status_changed(
        self,
        session_id: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Emit a session status change event.

        Args:
            session_id: The session ID.
            status: New status.
            details: Optional additional details.
        """
        event = ServerEvent(
            type=EventType.SESSION_STATUS_CHANGED,
            session_id=session_id,
            payload={
                "status": status,
                **(details or {}),
            },
        )
        await self._broadcast_event(session_id, event)

    async def emit_client_connected(
        self,
        session_id: str | None,
        client_count: int,
    ) -> None:
        """Emit a client connected event.

        Args:
            session_id: The session ID (None for global).
            client_count: Current number of connected clients.
        """
        event = ServerEvent(
            type=EventType.CONNECTED,
            session_id=session_id,
            payload={
                "client_count": client_count,
            },
        )
        await self._broadcast_event(session_id, event)

    async def _broadcast_event(self, session_id: str | None, event: ServerEvent) -> None:
        """Broadcast an event to all relevant clients.

        Args:
            session_id: Target session ID (None for global broadcast).
            event: The event to broadcast.
        """
        # Broadcast via SSE
        event_emitter = get_event_emitter()
        await event_emitter.emit(event)

        # Broadcast via WebSocket
        connection_manager = get_connection_manager()
        message = {
            "type": "event",
            "timestamp": event.timestamp.isoformat(),
            "payload": {
                "kind": event.type.value,
                "session_id": event.session_id,
                **event.payload,
            },
        }

        if session_id:
            await connection_manager.send_to_session(session_id, message)
        else:
            await connection_manager.broadcast(message)


# Global event bridge instance
_event_bridge: EventBridge | None = None


def get_event_bridge() -> EventBridge:
    """Get the global event bridge."""
    global _event_bridge
    if _event_bridge is None:
        _event_bridge = EventBridge()
    return _event_bridge


async def emit_tool_event(
    session_id: str,
    event_type: str,
    tool_name: str,
    **kwargs,
) -> None:
    """Convenience function to emit tool events.

    Args:
        session_id: The session ID.
        event_type: Type of event ('start', 'complete', 'error').
        tool_name: Name of the tool.
        **kwargs: Additional event data.
    """
    bridge = get_event_bridge()

    if event_type == "start":
        await bridge.emit_tool_call_start(
            session_id,
            tool_name,
            kwargs.get("arguments", {}),
        )
    elif event_type == "complete":
        await bridge.emit_tool_call_complete(
            session_id,
            tool_name,
            kwargs.get("result", ""),
            success=True,
            duration_ms=kwargs.get("duration_ms"),
        )
    elif event_type == "error":
        await bridge.emit_tool_call_complete(
            session_id,
            tool_name,
            kwargs.get("error", "Unknown error"),
            success=False,
            duration_ms=kwargs.get("duration_ms"),
        )
