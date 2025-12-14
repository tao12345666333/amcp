from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from .config import Server


def _expand_env(value: str) -> str:
    # Expand $VARS and ${VARS}
    return os.path.expandvars(value)


def _headers_with_env(headers: dict[str, str]) -> dict[str, str]:
    return {k: _expand_env(v) for k, v in headers.items()}


@asynccontextmanager
async def _open_transport(server: Server):
    """Yield (read, write) streams for the given server, regardless of transport."""
    if server.url:
        url = _expand_env(server.url)
        headers = _headers_with_env(server.headers)
        # StreamableHTTP returns (read, write, get_session_id)
        async with streamablehttp_client(url=url, headers=headers) as (read, write, _get):
            yield read, write
        return
    # default to stdio: merge env with current process env and expand variables
    base_env = dict(os.environ)
    merged = dict(base_env)
    for k, v in (server.env or {}).items():
        merged[str(k)] = _expand_env(str(v))

    params = StdioServerParameters(command=server.command or "", args=server.args, env=merged)

    # Suppress MCP server stderr by redirecting to devnull
    with open(os.devnull, "w") as devnull:
        async with stdio_client(params, errlog=devnull) as (read, write):
            yield read, write


async def list_mcp_tools(server: Server) -> list[dict[str, Any]]:
    async with _open_transport(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.list_tools()
        tools: list[dict[str, Any]] = []
        for t in result.tools:
            schema = None
            try:
                raw_schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)
                if raw_schema is not None:
                    if hasattr(raw_schema, "model_dump"):
                        schema = raw_schema.model_dump(by_alias=True, exclude_none=True)
                    elif hasattr(raw_schema, "to_dict"):
                        schema = raw_schema.to_dict()
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


async def call_mcp_tool(server: Server, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        async with _open_transport(server) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

            def _to_dict(x: Any) -> Any:
                if hasattr(x, "model_dump"):
                    return x.model_dump(by_alias=True, exclude_none=True)
                if hasattr(x, "to_dict"):
                    return x.to_dict()
                return x

            return {
                "tool": tool_name,
                "is_error": bool(getattr(result, "isError", False)),
                "content": [_to_dict(c) for c in (result.content or [])],
                "structuredContent": getattr(result, "structuredContent", None),
                "metadata": getattr(result, "meta", None) or {},
            }
    except* Exception as eg:
        # Handle ExceptionGroup from TaskGroup
        errors = [str(e) for e in eg.exceptions]
        raise Exception(f"MCP tool call failed: {'; '.join(errors)}") from eg
