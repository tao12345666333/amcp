"""Tests for protocol unification module."""

from __future__ import annotations

from datetime import datetime

import pytest

from amcp.protocol import (
    ErrorCode,
    ProtocolAdapter,
    ProtocolError,
    acp_event_to_server_event,
    get_protocol_adapter,
    server_event_to_acp_event,
    server_event_to_ws_message,
    ws_message_to_server_event,
)
from amcp.protocol.error_codes import (
    SessionBusyError,
    SessionNotFoundError,
    ToolNotFoundError,
    ValidationError,
)
from amcp.server.models import EventType, ServerEvent


class TestErrorCodes:
    """Tests for error codes module."""

    def test_error_code_to_http_status(self):
        """Test error code to HTTP status mapping."""
        assert ErrorCode.BAD_REQUEST.to_http_status() == 400
        assert ErrorCode.UNAUTHORIZED.to_http_status() == 401
        assert ErrorCode.FORBIDDEN.to_http_status() == 403
        assert ErrorCode.SESSION_NOT_FOUND.to_http_status() == 404
        assert ErrorCode.SESSION_BUSY.to_http_status() == 409
        assert ErrorCode.RATE_LIMITED.to_http_status() == 429
        assert ErrorCode.INTERNAL_ERROR.to_http_status() == 500
        assert ErrorCode.TIMEOUT.to_http_status() == 504

    def test_protocol_error_to_dict(self):
        """Test ProtocolError to dict conversion."""
        error = ProtocolError(
            code=ErrorCode.SESSION_NOT_FOUND,
            message="Session not found",
            details={"session_id": "abc123"},
        )
        result = error.to_dict()

        assert result["error"] == "Session not found"
        assert result["code"] == "SESSION_NOT_FOUND"
        assert result["details"]["session_id"] == "abc123"

    def test_protocol_error_to_http_response(self):
        """Test ProtocolError to HTTP response."""
        error = ProtocolError(
            code=ErrorCode.SESSION_BUSY,
            message="Session is busy",
        )
        body, status = error.to_http_response()

        assert status == 409
        assert body["error"] == "Session is busy"
        assert body["code"] == "SESSION_BUSY"

    def test_protocol_error_to_ws_message(self):
        """Test ProtocolError to WebSocket message."""
        error = ProtocolError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid field",
        )
        ws_msg = error.to_ws_message("msg-123")

        assert ws_msg["type"] == "error"
        assert ws_msg["id"] == "msg-123"
        assert ws_msg["payload"]["error"] == "Invalid field"
        assert ws_msg["payload"]["code"] == "VALIDATION_ERROR"

    def test_session_not_found_error(self):
        """Test SessionNotFoundError convenience class."""
        error = SessionNotFoundError("session-abc")

        assert error.code == ErrorCode.SESSION_NOT_FOUND
        assert "session-abc" in error.message
        assert error.details["session_id"] == "session-abc"

    def test_session_busy_error(self):
        """Test SessionBusyError convenience class."""
        error = SessionBusyError("session-123")

        assert error.code == ErrorCode.SESSION_BUSY
        assert "session-123" in error.message

    def test_tool_not_found_error(self):
        """Test ToolNotFoundError convenience class."""
        error = ToolNotFoundError("unknown_tool")

        assert error.code == ErrorCode.TOOL_NOT_FOUND
        assert "unknown_tool" in error.message

    def test_validation_error(self):
        """Test ValidationError convenience class."""
        error = ValidationError("Invalid email", field="email")

        assert error.code == ErrorCode.VALIDATION_ERROR
        assert "Invalid email" in error.message
        assert error.details["field"] == "email"


class TestConverters:
    """Tests for protocol converters."""

    def test_acp_agent_message_to_server_event(self):
        """Test converting ACP agent_message to ServerEvent."""
        acp_event = {
            "session_update": "agent_message",
            "content": [{"type": "text", "text": "Hello world"}],
        }

        event = acp_event_to_server_event(acp_event, "session-123")

        assert event.type == EventType.MESSAGE_CHUNK
        assert event.session_id == "session-123"
        assert event.payload["content"] == "Hello world"
        assert event.payload["done"] is False

    def test_acp_agent_response_to_server_event(self):
        """Test converting ACP agent_response to ServerEvent."""
        acp_event = {
            "session_update": "agent_response",
            "content": [{"type": "text", "text": "Done!"}],
        }

        event = acp_event_to_server_event(acp_event)

        assert event.type == EventType.MESSAGE_COMPLETE
        assert event.payload["done"] is True

    def test_acp_tool_call_start_to_server_event(self):
        """Test converting ACP tool_call_start to ServerEvent."""
        acp_event = {
            "session_update": "tool_call_start",
            "tool_call_id": "call_abc",
            "title": "Reading file",
            "kind": "read",
        }

        event = acp_event_to_server_event(acp_event, "session-123")

        assert event.type == EventType.TOOL_CALL_START
        assert event.payload["tool_call_id"] == "call_abc"
        assert event.payload["title"] == "Reading file"
        assert event.payload["kind"] == "read"

    def test_acp_tool_call_update_to_server_event(self):
        """Test converting ACP tool_call_update to ServerEvent."""
        acp_event = {
            "session_update": "tool_call_update",
            "tool_call_id": "call_abc",
            "status": "completed",
            "content": [{"type": "content", "content": {"type": "text", "text": "file contents"}}],
        }

        event = acp_event_to_server_event(acp_event)

        assert event.type == EventType.TOOL_CALL_COMPLETE
        assert event.payload["tool_call_id"] == "call_abc"
        assert event.payload["status"] == "completed"
        assert event.payload["result"] == "file contents"

    def test_server_event_to_acp_message(self):
        """Test converting ServerEvent to ACP format."""
        event = ServerEvent(
            type=EventType.MESSAGE_CHUNK,
            session_id="session-123",
            payload={"content": "Hello"},
        )

        acp = server_event_to_acp_event(event)

        assert acp["session_update"] == "agent_message"
        assert len(acp["content"]) == 1
        assert acp["content"][0]["type"] == "text"
        assert acp["content"][0]["text"] == "Hello"

    def test_server_event_to_acp_tool_start(self):
        """Test converting tool start event to ACP."""
        event = ServerEvent(
            type=EventType.TOOL_CALL_START,
            session_id="session-123",
            payload={
                "tool_call_id": "call_abc",
                "title": "Reading",
                "kind": "read",
            },
        )

        acp = server_event_to_acp_event(event)

        assert acp["session_update"] == "tool_call_start"
        assert acp["tool_call_id"] == "call_abc"
        assert acp["kind"] == "read"

    def test_server_event_to_ws_message(self):
        """Test converting ServerEvent to WebSocket message."""
        event = ServerEvent(
            type=EventType.MESSAGE_CHUNK,
            session_id="session-123",
            timestamp=datetime(2026, 1, 8, 12, 0, 0),
            payload={"content": "Hello", "done": False},
        )

        ws = server_event_to_ws_message(event, "msg-123")

        assert ws["type"] == "response"
        assert ws["id"] == "msg-123"
        assert ws["payload"]["kind"] == "text"
        assert ws["payload"]["content"] == "Hello"
        assert ws["payload"]["done"] is False
        assert ws["payload"]["session_id"] == "session-123"

    def test_server_event_to_ws_tool_event(self):
        """Test converting tool event to WebSocket message."""
        event = ServerEvent(
            type=EventType.TOOL_CALL_START,
            session_id="session-123",
            payload={
                "tool_name": "read_file",
                "tool_call_id": "call_abc",
                "arguments": {"path": "/src/main.py"},
            },
        )

        ws = server_event_to_ws_message(event)

        assert ws["type"] == "event"
        assert ws["payload"]["kind"] == "tool_call"
        assert ws["payload"]["tool_name"] == "read_file"
        assert ws["payload"]["arguments"]["path"] == "/src/main.py"

    def test_server_event_to_ws_error(self):
        """Test converting error event to WebSocket message."""
        event = ServerEvent(
            type=EventType.MESSAGE_ERROR,
            session_id="session-123",
            payload={"error": "Something went wrong", "code": "INTERNAL_ERROR"},
        )

        ws = server_event_to_ws_message(event)

        assert ws["type"] == "error"
        assert ws["payload"]["error"] == "Something went wrong"

    def test_ws_message_to_server_event(self):
        """Test converting WebSocket message to ServerEvent."""
        ws_msg = {
            "type": "request",
            "id": "msg-123",
            "timestamp": "2026-01-08T12:00:00",
            "payload": {
                "action": "prompt",
                "content": "Hello",
                "session_id": "session-123",
            },
        }

        event = ws_message_to_server_event(ws_msg)

        assert event is not None
        assert event.type == EventType.MESSAGE_START
        assert event.payload["action"] == "prompt"
        assert event.payload["session_id"] == "session-123"

    def test_ws_message_invalid_returns_none(self):
        """Test invalid WebSocket message returns None."""
        event = ws_message_to_server_event({"invalid": "message"})
        # Should return None for invalid messages
        assert event is None


class TestProtocolAdapter:
    """Tests for ProtocolAdapter class."""

    def test_get_protocol_adapter_singleton(self):
        """Test that get_protocol_adapter returns singleton."""
        adapter1 = get_protocol_adapter()
        adapter2 = get_protocol_adapter()
        assert adapter1 is adapter2

    def test_adapter_from_acp_event(self):
        """Test adapter ACP event conversion."""
        adapter = ProtocolAdapter()
        acp_event = {
            "session_update": "agent_message",
            "content": [{"type": "text", "text": "Hello"}],
        }

        event = adapter.from_acp_event(acp_event, "session-123")

        assert event.type == EventType.MESSAGE_CHUNK
        assert event.session_id == "session-123"

    def test_adapter_to_acp_event(self):
        """Test adapter to ACP event conversion."""
        adapter = ProtocolAdapter()
        event = ServerEvent(
            type=EventType.MESSAGE_CHUNK,
            payload={"content": "Hello"},
        )

        acp = adapter.to_acp_event(event)

        assert acp["session_update"] == "agent_message"

    def test_adapter_to_ws_message(self):
        """Test adapter to WebSocket message."""
        adapter = ProtocolAdapter()
        event = ServerEvent(
            type=EventType.MESSAGE_CHUNK,
            session_id="session-123",
            payload={"content": "Hello"},
        )

        ws = adapter.to_ws_message(event, "msg-123")

        assert ws["type"] == "response"
        assert ws["id"] == "msg-123"

    def test_adapter_create_ws_error(self):
        """Test adapter create WebSocket error."""
        adapter = ProtocolAdapter()
        error = SessionNotFoundError("session-abc")

        ws = adapter.create_ws_error(error, "msg-123")

        assert ws["type"] == "error"
        assert ws["id"] == "msg-123"
        assert ws["payload"]["code"] == "SESSION_NOT_FOUND"

    def test_adapter_create_http_error(self):
        """Test adapter create HTTP error."""
        adapter = ProtocolAdapter()
        error = SessionBusyError("session-123")

        body, status = adapter.create_http_error(error)

        assert status == 409
        assert body["code"] == "SESSION_BUSY"

    def test_adapter_to_sse_data(self):
        """Test adapter to SSE data format."""
        adapter = ProtocolAdapter()
        event = ServerEvent(
            type=EventType.MESSAGE_CHUNK,
            session_id="session-123",
            payload={"content": "Hello"},
        )

        sse = adapter.to_sse_data(event)

        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        assert '"type": "message.chunk"' in sse

    def test_adapter_create_message_event(self):
        """Test adapter create message event."""
        adapter = ProtocolAdapter()

        event = adapter.create_message_event(
            session_id="session-123",
            content="Hello world",
            done=False,
        )

        assert event.type == EventType.MESSAGE_CHUNK
        assert event.session_id == "session-123"
        assert event.payload["content"] == "Hello world"
        assert event.payload["done"] is False

    def test_adapter_create_message_event_complete(self):
        """Test adapter create complete message event."""
        adapter = ProtocolAdapter()

        event = adapter.create_message_event(
            session_id="session-123",
            content="Done!",
            done=True,
        )

        assert event.type == EventType.MESSAGE_COMPLETE
        assert event.payload["done"] is True

    def test_adapter_create_tool_start_event(self):
        """Test adapter create tool start event."""
        adapter = ProtocolAdapter()

        event = adapter.create_tool_start_event(
            session_id="session-123",
            tool_name="read_file",
            arguments={"path": "/test.py"},
        )

        assert event.type == EventType.TOOL_CALL_START
        assert event.payload["tool_name"] == "read_file"
        assert event.payload["arguments"]["path"] == "/test.py"
        assert "tool_call_id" in event.payload

    def test_adapter_create_tool_complete_event(self):
        """Test adapter create tool complete event."""
        adapter = ProtocolAdapter()

        event = adapter.create_tool_complete_event(
            session_id="session-123",
            tool_name="read_file",
            result="file contents",
            call_id="call_abc",
            success=True,
        )

        assert event.type == EventType.TOOL_CALL_COMPLETE
        assert event.payload["tool_name"] == "read_file"
        assert event.payload["result"] == "file contents"
        assert event.payload["success"] is True

    def test_adapter_create_tool_error_event(self):
        """Test adapter create tool error event."""
        adapter = ProtocolAdapter()

        event = adapter.create_tool_complete_event(
            session_id="session-123",
            tool_name="read_file",
            result="",
            call_id="call_abc",
            success=False,
            error="File not found",
        )

        assert event.type == EventType.TOOL_CALL_ERROR
        assert event.payload["success"] is False
        assert event.payload["error"] == "File not found"

    def test_adapter_create_session_event(self):
        """Test adapter create session event."""
        adapter = ProtocolAdapter()

        event = adapter.create_session_event(
            event_type=EventType.SESSION_CREATED,
            session_id="session-123",
            cwd="/my/project",
        )

        assert event.type == EventType.SESSION_CREATED
        assert event.session_id == "session-123"
        assert event.payload["cwd"] == "/my/project"

    def test_adapter_wrap_error_protocol_error(self):
        """Test adapter wrap error with ProtocolError."""
        adapter = ProtocolAdapter()
        error = SessionNotFoundError("session-abc")

        wrapped = adapter.wrap_error(error)

        assert wrapped is error

    def test_adapter_wrap_error_generic(self):
        """Test adapter wrap generic error."""
        adapter = ProtocolAdapter()
        error = ValueError("Something went wrong")

        wrapped = adapter.wrap_error(error)

        assert isinstance(wrapped, ProtocolError)
        assert wrapped.code == ErrorCode.INTERNAL_ERROR
        assert "Something went wrong" in wrapped.message

    def test_adapter_wrap_error_custom_code(self):
        """Test adapter wrap error with custom code."""
        adapter = ProtocolAdapter()
        error = ValueError("Invalid input")

        wrapped = adapter.wrap_error(error, default_code=ErrorCode.VALIDATION_ERROR)

        assert wrapped.code == ErrorCode.VALIDATION_ERROR


class TestRoundTrip:
    """Test round-trip conversions."""

    def test_message_roundtrip_acp(self):
        """Test message event ACP round-trip."""
        original = ServerEvent(
            type=EventType.MESSAGE_CHUNK,
            session_id="session-123",
            payload={"content": "Hello world"},
        )

        # To ACP and back
        acp = server_event_to_acp_event(original)
        restored = acp_event_to_server_event(acp, "session-123")

        assert restored.type == original.type
        assert restored.session_id == original.session_id
        assert restored.payload["content"] == original.payload["content"]

    def test_tool_start_roundtrip_acp(self):
        """Test tool start event ACP round-trip."""
        original = ServerEvent(
            type=EventType.TOOL_CALL_START,
            session_id="session-123",
            payload={
                "tool_call_id": "call_abc",
                "title": "Reading file",
                "kind": "read",
            },
        )

        # To ACP and back
        acp = server_event_to_acp_event(original)
        restored = acp_event_to_server_event(acp, "session-123")

        assert restored.type == original.type
        assert restored.payload["tool_call_id"] == original.payload["tool_call_id"]
        assert restored.payload["kind"] == original.payload["kind"]
