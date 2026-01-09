"""Tool management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..models import ToolInfo, ToolListResponse

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=ToolListResponse)
async def list_tools() -> ToolListResponse:
    """List all available tools.

    Returns both built-in tools and MCP tools.
    """
    from ...tools import get_tool_registry

    tool_registry = get_tool_registry()
    tool_names = tool_registry.list_tools()

    tool_infos = []
    for tool_name in tool_names:
        # Get tool function
        tool_func = tool_registry.get_tool(tool_name)

        # Get description from docstring or empty
        description = ""
        if tool_func and hasattr(tool_func, "__doc__") and tool_func.__doc__:
            description = tool_func.__doc__.split("\n")[0]

        # Determine source
        source = "builtin"
        if "mcp" in tool_name.lower():
            source = "mcp"

        tool_infos.append(
            ToolInfo(
                name=tool_name,
                description=description,
                parameters={},
                source=source,
            )
        )

    return ToolListResponse(tools=tool_infos, total=len(tool_infos))


@router.get("/{tool_name}")
async def get_tool(tool_name: str) -> ToolInfo:
    """Get details for a specific tool."""
    from ...tools import get_tool_registry

    tool_registry = get_tool_registry()
    tool_func = tool_registry.get_tool(tool_name)

    if tool_func is None:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Tool not found: {tool_name}", "code": "TOOL_NOT_FOUND"},
        )

    # Get description from docstring
    description = ""
    if tool_func and hasattr(tool_func, "__doc__") and tool_func.__doc__:
        description = tool_func.__doc__.split("\n")[0]

    return ToolInfo(
        name=tool_name,
        description=description,
        parameters={},
        source="builtin",
    )


@router.post("/{tool_name}/execute")
async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> dict:
    """Execute a tool directly.

    This is mainly for testing purposes. In normal operation,
    tools are executed as part of agent conversations.

    Warning: This bypasses normal safety checks.
    """
    from ...tools import ToolResult, get_tool_registry

    tool_registry = get_tool_registry()
    tool_func = tool_registry.get_tool(tool_name)

    if tool_func is None:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Tool not found: {tool_name}", "code": "TOOL_NOT_FOUND"},
        )

    try:
        result = tool_func.execute(**arguments)

        if isinstance(result, ToolResult):
            return {
                "success": result.success,
                "result": result.content,
                "error": result.error,
            }
        else:
            return {
                "success": True,
                "result": str(result),
                "error": None,
            }

    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": str(e),
        }


@router.get("/categories")
async def list_tool_categories() -> dict:
    """List tools grouped by category."""
    from ...tools import get_tool_registry

    tool_registry = get_tool_registry()
    tool_names = tool_registry.list_tools()

    categories: dict[str, list[str]] = {
        "file": [],
        "code": [],
        "shell": [],
        "web": [],
        "mcp": [],
        "other": [],
    }

    for tool_name in tool_names:
        name_lower = tool_name.lower()

        if any(k in name_lower for k in ["file", "read", "write", "edit"]):
            categories["file"].append(tool_name)
        elif any(k in name_lower for k in ["code", "lint", "format", "grep"]):
            categories["code"].append(tool_name)
        elif any(k in name_lower for k in ["bash", "shell", "command", "exec"]):
            categories["shell"].append(tool_name)
        elif any(k in name_lower for k in ["web", "browse", "fetch", "http"]):
            categories["web"].append(tool_name)
        elif "mcp" in name_lower:
            categories["mcp"].append(tool_name)
        else:
            categories["other"].append(tool_name)

    return {
        "categories": categories,
        "total": len(tool_names),
    }
