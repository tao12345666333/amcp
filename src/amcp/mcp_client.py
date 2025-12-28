"""MCP client implementation using fastmcp library.

This module provides functions to interact with MCP servers using the fastmcp library,
which provides a high-level, Pythonic interface for MCP protocol operations.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from .config import Server

# Default timeout in seconds for MCP operations
DEFAULT_MCP_TIMEOUT = 180.0  # 180 seconds (3 minutes) default timeout
DEFAULT_LIST_TOOLS_TIMEOUT = 30.0  # 30 seconds for listing tools


def _expand_env(value: str) -> str:
    """Expand $VARS and ${VARS} in environment variable values."""
    return os.path.expandvars(value)


def _headers_with_env(headers: dict[str, str]) -> dict[str, str]:
    """Expand environment variables in header values."""
    return {k: _expand_env(v) for k, v in headers.items()}


def _create_client(server: Server) -> Client:
    """Create a FastMCP client for the given server configuration.

    Automatically selects the appropriate transport based on server config:
    - If server.url is set: use StreamableHttpTransport
    - Otherwise: use StdioTransport with command/args
    """
    if server.url:
        # HTTP/StreamableHTTP transport
        url = _expand_env(server.url)
        headers = _headers_with_env(server.headers)
        transport = StreamableHttpTransport(url=url, headers=headers)
        return Client(transport)

    # Stdio transport: merge env with current process env and expand variables
    base_env = dict(os.environ)
    merged = dict(base_env)
    for k, v in (server.env or {}).items():
        merged[str(k)] = _expand_env(str(v))

    transport = StdioTransport(
        command=server.command or "",
        args=list(server.args) if server.args else [],
        env=merged,
    )
    return Client(transport)


class MCPTimeoutError(Exception):
    """Exception raised when an MCP operation times out."""

    def __init__(self, operation: str, timeout: float, message: str | None = None):
        self.operation = operation
        self.timeout = timeout
        if message:
            super().__init__(message)
        else:
            super().__init__(f"MCP operation '{operation}' timed out after {timeout:.1f} seconds")


async def list_mcp_tools(
    server: Server,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """List all tools available from an MCP server.

    Args:
        server: Server configuration with connection details.
        timeout: Optional timeout in seconds. Defaults to DEFAULT_LIST_TOOLS_TIMEOUT (30s).

    Returns:
        List of tool definitions with name, description, and inputSchema.

    Raises:
        MCPTimeoutError: If the operation times out.
    """
    timeout = timeout if timeout is not None else DEFAULT_LIST_TOOLS_TIMEOUT

    async def _list_tools() -> list[dict[str, Any]]:
        client = _create_client(server)
        async with client:
            result = await client.list_tools()
            tools: list[dict[str, Any]] = []
            for t in result:
                schema = None
                try:
                    # Handle different schema representations
                    raw_schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)
                    if raw_schema is not None:
                        if hasattr(raw_schema, "model_dump"):
                            schema = raw_schema.model_dump(by_alias=True, exclude_none=True)
                        elif hasattr(raw_schema, "to_dict"):
                            schema = raw_schema.to_dict()
                        elif isinstance(raw_schema, dict):
                            schema = raw_schema
                        else:
                            schema = raw_schema
                except Exception:
                    schema = None
                tools.append(
                    {
                        "name": t.name,
                        "description": (t.description or ""),
                        "inputSchema": schema,
                    }
                )
            return tools

    try:
        return await asyncio.wait_for(_list_tools(), timeout=timeout)
    except TimeoutError:
        raise MCPTimeoutError("list_tools", timeout) from None


async def call_mcp_tool(
    server: Server,
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float | None = None,
) -> dict[str, Any]:
    """Call a tool on an MCP server.

    Args:
        server: Server configuration with connection details.
        tool_name: Name of the tool to call.
        arguments: Arguments to pass to the tool.
        timeout: Optional timeout in seconds. Defaults to DEFAULT_MCP_TIMEOUT (60s).

    Returns:
        Dict with tool response including:
        - tool: Name of the tool called
        - is_error: Whether the call resulted in an error
        - content: List of content items from the response
        - structuredContent: Any structured content from the response
        - metadata: Additional metadata from the response

    Raises:
        MCPTimeoutError: If the operation times out.
        Exception: If the tool call fails for other reasons.
    """
    timeout = timeout if timeout is not None else DEFAULT_MCP_TIMEOUT

    async def _call_tool() -> dict[str, Any]:
        client = _create_client(server)
        async with client:
            result = await client.call_tool(tool_name, arguments)

            def _to_dict(x: Any) -> Any:
                if hasattr(x, "model_dump"):
                    return x.model_dump(by_alias=True, exclude_none=True)
                if hasattr(x, "to_dict"):
                    return x.to_dict()
                return x

            # fastmcp returns a CallToolResult with content attribute
            content = result.content if hasattr(result, "content") else []
            is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))

            return {
                "tool": tool_name,
                "is_error": is_error,
                "content": [_to_dict(c) for c in (content or [])],
                "structuredContent": getattr(result, "structuredContent", None),
                "metadata": getattr(result, "meta", None) or {},
            }

    try:
        return await asyncio.wait_for(_call_tool(), timeout=timeout)
    except TimeoutError:
        raise MCPTimeoutError(
            tool_name,
            timeout,
            f"MCP tool '{tool_name}' timed out after {timeout:.1f} seconds. "
            "The server may be unresponsive or the operation is taking too long.",
        ) from None
    except BaseExceptionGroup as eg:
        # Handle ExceptionGroup from TaskGroup
        errors = [str(e) for e in eg.exceptions]
        raise Exception(f"MCP tool call failed: {'; '.join(errors)}") from eg
    except Exception as e:
        raise Exception(f"MCP tool call failed: {e}") from e

