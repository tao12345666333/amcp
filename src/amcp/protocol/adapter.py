"""Protocol Adapter for unifying ACP, HTTP, and WebSocket protocols.

This module provides the ProtocolAdapter class that serves as a bridge
between different protocols, ensuring consistent behavior and event handling.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..server.models import EventType, ServerEvent
from .converters import (
    acp_event_to_server_event,
    server_event_to_acp_event,
    server_event_to_ws_message,
)
from .error_codes import ErrorCode, ProtocolError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ..server.session_manager import ManagedSession


class ProtocolAdapter:
    """Adapter for converting between different protocols.

    This class provides a unified interface for:
    - Converting events between ACP, HTTP, and WebSocket formats
    - Handling errors consistently across protocols
    - Managing session lifecycles across protocols

    Example:
        >>> adapter = ProtocolAdapter()
        >>>
        >>> # Convert ACP event to our format
        >>> acp_event = {"session_update": "agent_message", "content": [...]}
        >>> server_event = adapter.from_acp_event(acp_event, "session-123")
        >>>
        >>> # Convert to WebSocket format for clients
        >>> ws_message = adapter.to_ws_message(server_event)
    """

    def __init__(self):
        """Initialize the protocol adapter."""
        self._event_handlers: dict[EventType, list[Callable[[ServerEvent], None]]] = {}

    # =========================================================================
    # ACP Protocol Methods
    # =========================================================================

    def from_acp_event(
        self,
        acp_event: dict[str, Any],
        session_id: str | None = None,
    ) -> ServerEvent:
        """Convert an ACP event to a ServerEvent.

        Args:
            acp_event: The ACP event dictionary.
            session_id: Optional session ID.

        Returns:
            Unified ServerEvent.
        """
        return acp_event_to_server_event(acp_event, session_id)

    def to_acp_event(self, event: ServerEvent) -> dict[str, Any]:
        """Convert a ServerEvent to an ACP event.

        Args:
            event: The ServerEvent to convert.

        Returns:
            ACP-compatible event dictionary.
        """
        return server_event_to_acp_event(event)

    # =========================================================================
    # WebSocket Protocol Methods
    # =========================================================================

    def to_ws_message(
        self,
        event: ServerEvent,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Convert a ServerEvent to a WebSocket message.

        Args:
            event: The ServerEvent to convert.
            message_id: Optional message ID for correlation.

        Returns:
            WebSocket message dictionary.
        """
        return server_event_to_ws_message(event, message_id)

    def create_ws_error(
        self,
        error: ProtocolError,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a WebSocket error message.

        Args:
            error: The protocol error.
            message_id: Optional message ID for correlation.

        Returns:
            WebSocket error message.
        """
        return error.to_ws_message(message_id)

    # =========================================================================
    # HTTP Protocol Methods
    # =========================================================================

    def create_http_error(self, error: ProtocolError) -> tuple[dict[str, Any], int]:
        """Create an HTTP error response.

        Args:
            error: The protocol error.

        Returns:
            Tuple of (response_body, status_code).
        """
        return error.to_http_response()

    def to_sse_data(self, event: ServerEvent) -> str:
        """Convert a ServerEvent to SSE data format.

        Args:
            event: The ServerEvent to convert.

        Returns:
            SSE formatted data string.
        """
        import json

        data = {
            "type": event.type.value,
            "session_id": event.session_id,
            "timestamp": event.timestamp.isoformat(),
            "payload": event.payload,
        }
        return f"data: {json.dumps(data)}\n\n"

    # =========================================================================
    # Event Factory Methods
    # =========================================================================

    def create_message_event(
        self,
        session_id: str,
        content: str,
        message_id: str | None = None,
        done: bool = False,
    ) -> ServerEvent:
        """Create a message event.

        Args:
            session_id: The session ID.
            content: The message content.
            message_id: Optional message ID.
            done: Whether this is the final message.

        Returns:
            ServerEvent for the message.
        """
        event_type = EventType.MESSAGE_COMPLETE if done else EventType.MESSAGE_CHUNK
        return ServerEvent(
            type=event_type,
            session_id=session_id,
            timestamp=datetime.now(),
            payload={
                "content": content,
                "message_id": message_id or uuid4().hex,
                "done": done,
            },
        )

    def create_tool_start_event(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        call_id: str | None = None,
    ) -> ServerEvent:
        """Create a tool call start event.

        Args:
            session_id: The session ID.
            tool_name: Name of the tool being called.
            arguments: Tool arguments.
            call_id: Optional call ID for tracking.

        Returns:
            ServerEvent for tool call start.
        """
        return ServerEvent(
            type=EventType.TOOL_CALL_START,
            session_id=session_id,
            timestamp=datetime.now(),
            payload={
                "tool_name": tool_name,
                "arguments": arguments,
                "tool_call_id": call_id or f"call_{uuid4().hex[:8]}",
            },
        )

    def create_tool_complete_event(
        self,
        session_id: str,
        tool_name: str,
        result: str,
        call_id: str,
        success: bool = True,
        error: str | None = None,
    ) -> ServerEvent:
        """Create a tool call complete event.

        Args:
            session_id: The session ID.
            tool_name: Name of the tool.
            result: Tool execution result.
            call_id: The call ID from the start event.
            success: Whether execution was successful.
            error: Optional error message if failed.

        Returns:
            ServerEvent for tool call completion.
        """
        event_type = EventType.TOOL_CALL_COMPLETE if success else EventType.TOOL_CALL_ERROR
        return ServerEvent(
            type=event_type,
            session_id=session_id,
            timestamp=datetime.now(),
            payload={
                "tool_name": tool_name,
                "result": result,
                "tool_call_id": call_id,
                "success": success,
                "error": error,
            },
        )

    def create_session_event(
        self,
        event_type: EventType,
        session_id: str,
        **extra: Any,
    ) -> ServerEvent:
        """Create a session lifecycle event.

        Args:
            event_type: The session event type.
            session_id: The session ID.
            **extra: Additional payload data.

        Returns:
            ServerEvent for the session.
        """
        return ServerEvent(
            type=event_type,
            session_id=session_id,
            timestamp=datetime.now(),
            payload=extra,
        )

    # =========================================================================
    # Error Handling
    # =========================================================================

    def wrap_error(
        self,
        error: Exception,
        default_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
    ) -> ProtocolError:
        """Wrap an exception in a ProtocolError.

        Args:
            error: The exception to wrap.
            default_code: Default error code if not a ProtocolError.

        Returns:
            ProtocolError instance.
        """
        if isinstance(error, ProtocolError):
            return error
        return ProtocolError(
            code=default_code,
            message=str(error),
        )

    # =========================================================================
    # Session Lifecycle Helpers
    # =========================================================================

    async def session_to_response(
        self,
        session: ManagedSession,
    ) -> dict[str, Any]:
        """Convert a managed session to an API response.

        Args:
            session: The managed session.

        Returns:
            Session response dictionary.
        """
        return {
            "id": session.id,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "cwd": session.cwd,
            "agent_name": session.agent_name,
            "status": session.status.value,
            "message_count": session.message_count,
            "token_usage": {
                "prompt_tokens": session.token_usage.prompt_tokens,
                "completion_tokens": session.token_usage.completion_tokens,
                "total_tokens": session.token_usage.total_tokens,
            },
            "queued_count": session.agent.queued_count() if session.agent else 0,
        }

    # =========================================================================
    # Stream Adapters
    # =========================================================================

    async def adapt_stream(
        self,
        source: AsyncIterator[dict[str, Any]],
        protocol: str,
        session_id: str | None = None,
        message_id: str | None = None,
    ) -> AsyncIterator[Any]:
        """Adapt a stream to a specific protocol format.

        Args:
            source: The source async iterator.
            protocol: Target protocol ("ws", "sse", "acp").
            session_id: Optional session ID.
            message_id: Optional message ID.

        Yields:
            Formatted events for the target protocol.
        """
        async for item in source:
            # First, ensure we have a ServerEvent
            if isinstance(item, ServerEvent):
                event = item
            else:
                event = ServerEvent(
                    type=EventType.MESSAGE_CHUNK,
                    session_id=session_id,
                    payload=item,
                )

            # Convert to target format
            if protocol == "ws":
                yield self.to_ws_message(event, message_id)
            elif protocol == "sse":
                yield self.to_sse_data(event)
            elif protocol == "acp":
                yield self.to_acp_event(event)
            else:
                yield event


# Global adapter instance
_adapter: ProtocolAdapter | None = None


def get_protocol_adapter() -> ProtocolAdapter:
    """Get the global protocol adapter instance.

    Returns:
        The protocol adapter.
    """
    global _adapter
    if _adapter is None:
        _adapter = ProtocolAdapter()
    return _adapter
