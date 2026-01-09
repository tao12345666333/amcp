"""Unified error codes across all protocols.

This module defines a consistent set of error codes that are used across
ACP, HTTP REST API, and WebSocket protocols.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Unified error codes for all protocols.

    These error codes are designed to be consistent across:
    - HTTP responses (mapped to appropriate status codes)
    - WebSocket error messages
    - ACP protocol errors
    """

    # =========================================================================
    # Client Errors (4xx equivalent)
    # =========================================================================

    # Request Errors
    BAD_REQUEST = "BAD_REQUEST"  # 400 - Invalid request format
    VALIDATION_ERROR = "VALIDATION_ERROR"  # 400 - Request validation failed
    INVALID_JSON = "INVALID_JSON"  # 400 - Malformed JSON

    # Authentication/Authorization Errors
    UNAUTHORIZED = "UNAUTHORIZED"  # 401 - Authentication required
    FORBIDDEN = "FORBIDDEN"  # 403 - Access denied
    INVALID_TOKEN = "INVALID_TOKEN"  # 401 - Token expired or invalid
    INVALID_API_KEY = "INVALID_API_KEY"  # 401 - API key invalid

    # Resource Errors
    NOT_FOUND = "NOT_FOUND"  # 404 - Resource not found
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"  # 404 - Session not found
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"  # 404 - Tool not found
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"  # 404 - Agent not found

    # Conflict Errors
    CONFLICT = "CONFLICT"  # 409 - Resource conflict
    SESSION_BUSY = "SESSION_BUSY"  # 409 - Session is busy
    ALREADY_EXISTS = "ALREADY_EXISTS"  # 409 - Resource already exists

    # Rate Limit Errors
    RATE_LIMITED = "RATE_LIMITED"  # 429 - Too many requests

    # =========================================================================
    # Server Errors (5xx equivalent)
    # =========================================================================

    INTERNAL_ERROR = "INTERNAL_ERROR"  # 500 - Internal server error
    LLM_ERROR = "LLM_ERROR"  # 500 - LLM API error
    TOOL_ERROR = "TOOL_ERROR"  # 500 - Tool execution error
    MCP_ERROR = "MCP_ERROR"  # 500 - MCP server error
    TIMEOUT = "TIMEOUT"  # 504 - Operation timed out

    # =========================================================================
    # Connection Errors
    # =========================================================================

    CONNECTION_CLOSED = "CONNECTION_CLOSED"  # Connection closed unexpectedly
    CONNECTION_FAILED = "CONNECTION_FAILED"  # Failed to establish connection

    # =========================================================================
    # Protocol Errors
    # =========================================================================

    PROTOCOL_ERROR = "PROTOCOL_ERROR"  # Protocol violation
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"  # Unsupported action
    INVALID_MESSAGE = "INVALID_MESSAGE"  # Invalid message format

    def to_http_status(self) -> int:
        """Convert error code to HTTP status code."""
        return ERROR_TO_HTTP_STATUS.get(self, 500)


# Mapping from error codes to HTTP status codes
ERROR_TO_HTTP_STATUS: dict[ErrorCode, int] = {
    # 400 Bad Request
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.INVALID_JSON: 400,
    ErrorCode.PROTOCOL_ERROR: 400,
    ErrorCode.UNSUPPORTED_ACTION: 400,
    ErrorCode.INVALID_MESSAGE: 400,
    # 401 Unauthorized
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.INVALID_TOKEN: 401,
    ErrorCode.INVALID_API_KEY: 401,
    # 403 Forbidden
    ErrorCode.FORBIDDEN: 403,
    # 404 Not Found
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.SESSION_NOT_FOUND: 404,
    ErrorCode.TOOL_NOT_FOUND: 404,
    ErrorCode.AGENT_NOT_FOUND: 404,
    # 409 Conflict
    ErrorCode.CONFLICT: 409,
    ErrorCode.SESSION_BUSY: 409,
    ErrorCode.ALREADY_EXISTS: 409,
    # 429 Rate Limited
    ErrorCode.RATE_LIMITED: 429,
    # 500 Internal Error
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.LLM_ERROR: 500,
    ErrorCode.TOOL_ERROR: 500,
    ErrorCode.MCP_ERROR: 500,
    ErrorCode.CONNECTION_CLOSED: 500,
    ErrorCode.CONNECTION_FAILED: 500,
    # 504 Gateway Timeout
    ErrorCode.TIMEOUT: 504,
}


class ProtocolError(Exception):
    """Base exception for protocol-related errors.

    This exception can be raised in any protocol handler and will be
    properly converted to the appropriate error format.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        """Initialize protocol error.

        Args:
            code: The error code.
            message: Human-readable error message.
            details: Optional additional error details.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary format."""
        result: dict[str, Any] = {
            "error": self.message,
            "code": self.code.value,
        }
        if self.details:
            result["details"] = self.details
        return result

    def to_http_response(self) -> tuple[dict[str, Any], int]:
        """Convert error to HTTP response format.

        Returns:
            Tuple of (response_body, status_code).
        """
        return self.to_dict(), self.code.to_http_status()

    def to_ws_message(self, message_id: str | None = None) -> dict[str, Any]:
        """Convert error to WebSocket message format.

        Args:
            message_id: Optional message ID for correlation.

        Returns:
            WebSocket error message.
        """
        return {
            "type": "error",
            "id": message_id,
            "payload": self.to_dict(),
        }


# ============================================================================
# Convenience exception classes
# ============================================================================


class SessionNotFoundError(ProtocolError):
    """Session not found error."""

    def __init__(self, session_id: str):
        super().__init__(
            code=ErrorCode.SESSION_NOT_FOUND,
            message=f"Session not found: {session_id}",
            details={"session_id": session_id},
        )


class SessionBusyError(ProtocolError):
    """Session is busy error."""

    def __init__(self, session_id: str):
        super().__init__(
            code=ErrorCode.SESSION_BUSY,
            message=f"Session is busy: {session_id}",
            details={"session_id": session_id},
        )


class ToolNotFoundError(ProtocolError):
    """Tool not found error."""

    def __init__(self, tool_name: str):
        super().__init__(
            code=ErrorCode.TOOL_NOT_FOUND,
            message=f"Tool not found: {tool_name}",
            details={"tool_name": tool_name},
        )


class ValidationError(ProtocolError):
    """Validation error."""

    def __init__(self, message: str, field: str | None = None):
        details = {"field": field} if field else {}
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            details=details,
        )
