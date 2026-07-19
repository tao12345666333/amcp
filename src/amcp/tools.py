"""Tool definitions and registry for AMCP."""

from __future__ import annotations

import asyncio
import os
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

import httpx
from rich.console import Console


@dataclass
class ToolResult:
    """Result of tool execution."""

    success: bool
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ToolError(Exception):
    """Base exception for tool errors."""

    pass


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""

    pass


class ToolValidationError(ToolError):
    """Raised when tool parameters are invalid."""

    pass


@runtime_checkable
class Tool(Protocol):
    """Protocol for tool implementations."""

    @property
    def name(self) -> str:
        """Tool name."""
        ...

    @property
    def description(self) -> str:
        """Tool description."""
        ...

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given parameters."""
        ...

    def get_spec(self) -> dict[str, Any]:
        """Get tool specification for LLM."""
        ...


class BaseTool(ABC):
    """Base class for tool implementations."""

    def __init__(self):
        self.console = Console()

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters."""
        pass

    def validate_parameters(self, **kwargs) -> None:  # noqa: B027
        """Validate tool parameters. Override in subclasses."""
        pass

    def get_spec(self) -> dict[str, Any]:
        """Get tool specification for LLM."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema(),
            },
        }

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get JSON schema for tool parameters. Override in subclasses."""
        return {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._tool_specs: dict[str, dict[str, Any]] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self._tool_specs[tool.name] = tool.get_spec() if hasattr(tool, "get_spec") else {}

    def unregister(self, name: str) -> None:
        """Unregister a tool."""
        self._tools.pop(name, None)
        self._tool_specs.pop(name, None)

    def get_tool(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_tool_specs(self) -> dict[str, dict[str, Any]]:
        """Get all tool specifications."""
        return self._tool_specs.copy()

    def execute_tool(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name."""
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(success=False, content="", error=f"Tool '{name}' not found")

        try:
            # Validate parameters
            if hasattr(tool, "validate_parameters"):
                tool.validate_parameters(**kwargs)

            # Execute tool
            result = tool.execute(**kwargs)
            return result

        except Exception as e:
            return ToolResult(success=False, content="", error=f"Tool execution failed: {type(e).__name__}: {e}")


def _run_coroutine_in_thread(coro: Any) -> Any:
    """Run a coroutine from synchronous tool code, even under an active event loop."""

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            error["value"] = exc

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    worker.join()

    if "value" in error:
        raise error["value"]
    return result.get("value")


def _truncate_text(value: str, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return value[: max_chars - 16].rstrip() + "\n...[truncated]"


_DEFAULT_EXA_MCP_URL = "https://mcp.exa.ai/mcp"
_DEFAULT_FIRECRAWL_MCP_URL = "https://mcp.firecrawl.dev/v2/mcp"


def _firecrawl_api_base() -> str:
    return (
        os.environ.get("AMCP_FIRECRAWL_API_URL") or os.environ.get("FIRECRAWL_API_URL") or "https://api.firecrawl.dev"
    ).rstrip("/")


def _firecrawl_api_key() -> str | None:
    return (
        os.environ.get("AMCP_FIRECRAWL_API_KEY")
        or os.environ.get("FIRECRAWL_API_KEY")
        or os.environ.get("FIRECRAWL_OAUTH_TOKEN")
    )


def _firecrawl_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = _firecrawl_api_key()
    if token:
        bearer = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        headers["Authorization"] = bearer
    return headers


def _call_firecrawl(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_firecrawl_api_base()}{path}"
    response = httpx.post(url, json=payload, headers=_firecrawl_headers(), timeout=60.0)
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


def _get_firecrawl_server_config():
    """Return the internal Firecrawl MCP server configuration.

    The built-in web tools use this as an implementation detail. The server is
    intentionally not part of the default user-visible MCP server list.
    """
    from dataclasses import replace

    from .config import Server, load_config

    cfg = load_config()
    server = cfg.servers.get("firecrawl") or Server(
        url=os.environ.get("AMCP_FIRECRAWL_MCP_URL") or _DEFAULT_FIRECRAWL_MCP_URL
    )
    token = _firecrawl_api_key()
    if token and not server.headers.get("Authorization") and not server.headers.get("authorization"):
        bearer = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        return replace(server, headers={**server.headers, "Authorization": bearer})
    return server


def _call_firecrawl_mcp(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a firecrawl MCP tool and parse the text payload as JSON.

    The hosted firecrawl MCP server returns search/scrape results as a JSON
    string inside a single text content item, mirroring the REST API shape
    (e.g. ``{"data": {"web": [...]}}`` for search). We parse it back into a
    dict so callers can reuse the existing REST response handling.
    """
    import json

    from .mcp_client import call_mcp_tool

    server = _get_firecrawl_server_config()
    response = cast(
        dict[str, Any],
        _run_coroutine_in_thread(call_mcp_tool(server, tool_name, arguments)),
    )
    if response.get("is_error"):
        text = _render_mcp_text_response("Web provider error", response)
        raise ToolExecutionError(text)

    for item in response.get("content", []) or []:
        if item.get("type") == "text":
            raw = str(item.get("text", "")).strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    # Merge metadata so callers can still inspect the MCP envelope.
                    parsed.setdefault("_mcp", response)
                    return parsed
            except json.JSONDecodeError:
                # Some tools return prose; surface it as a data field.
                return {"data": {"markdown": raw}, "_mcp": response}
    # No text content; fall back to the raw MCP envelope.
    return response


def _firecrawl_search(payload: dict[str, Any]) -> dict[str, Any]:
    """Run a firecrawl search via MCP (keyless) or REST (when an API key is set)."""
    if _firecrawl_api_key() is None:
        mcp_args: dict[str, Any] = {"query": payload.get("query", "")}
        if "limit" in payload:
            mcp_args["limit"] = payload["limit"]
        if "includeDomains" in payload:
            mcp_args["includeDomains"] = payload["includeDomains"]
        if "excludeDomains" in payload:
            mcp_args["excludeDomains"] = payload["excludeDomains"]
        scrape_options = payload.get("scrapeOptions")
        if scrape_options:
            mcp_args["scrapeOptions"] = scrape_options
        return _call_firecrawl_mcp("firecrawl_search", mcp_args)
    return _call_firecrawl("/v2/search", payload)


def _firecrawl_scrape(payload: dict[str, Any]) -> dict[str, Any]:
    """Run a firecrawl scrape via MCP (keyless) or REST (when an API key is set)."""
    if _firecrawl_api_key() is None:
        mcp_args: dict[str, Any] = {"url": payload.get("url", "")}
        if "formats" in payload:
            mcp_args["formats"] = payload["formats"]
        if "onlyMainContent" in payload:
            mcp_args["onlyMainContent"] = payload["onlyMainContent"]
        return _call_firecrawl_mcp("firecrawl_scrape", mcp_args)
    return _call_firecrawl("/v2/scrape", payload)


def _get_exa_server_config():
    from .config import Server, load_config

    cfg = load_config()
    return cfg.servers.get("exa") or Server(url=os.environ.get("AMCP_EXA_MCP_URL") or _DEFAULT_EXA_MCP_URL)


def _call_exa_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from .mcp_client import call_mcp_tool

    server = _get_exa_server_config()
    return cast(dict[str, Any], _run_coroutine_in_thread(call_mcp_tool(server, tool_name, arguments)))


def _render_mcp_text_response(prefix: str, response: dict[str, Any]) -> str:
    parts: list[str] = [prefix]
    for item in response.get("content", []) or []:
        if item.get("type") == "text":
            text = str(item.get("text", "")).strip()
            if text:
                parts.append(text)
    if len(parts) == 1:
        parts.append(str(response))
    return "\n\n".join(parts)


class WebSearchTool(BaseTool):
    """Search the live web."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the public internet for live documentation, libraries, APIs, current events, "
            "and web pages. Use this when you need current information from the web."
        )

    def execute(  # type: ignore[override]
        self,
        query: str,
        limit: int = 5,
        backend: str = "auto",
        fetch_content: bool = False,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> ToolResult:
        self.validate_parameters(
            query=query,
            limit=limit,
            backend=backend,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )

        domain_filtered = bool(include_domains or exclude_domains)
        errors: list[str] = []

        if backend in {"auto", "exa"} and not domain_filtered:
            try:
                exa_response = _call_exa_tool(
                    "web_search_exa",
                    {
                        "query": query,
                        "numResults": limit,
                        "type": "fast",
                    },
                )
                return ToolResult(
                    success=True,
                    content=_render_mcp_text_response(f"Web search results for: {query}", exa_response),
                    metadata={"backend": "exa", "response": exa_response},
                )
            except Exception:
                if backend == "exa":
                    return ToolResult(success=False, content="", error="web search provider failed")
                errors.append("primary web search provider failed")

        try:
            payload: dict[str, Any] = {
                "query": query,
                "limit": limit,
            }
            if include_domains:
                payload["includeDomains"] = include_domains
            if exclude_domains:
                payload["excludeDomains"] = exclude_domains
            if fetch_content:
                payload["scrapeOptions"] = {
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                }
            response = _firecrawl_search(payload)
            items = response.get("data", {}).get("web", []) or []

            lines = [f"Web search results for: {query}"]
            for idx, item in enumerate(items, start=1):
                title = str(item.get("title") or item.get("metadata", {}).get("title") or "Untitled")
                url = str(item.get("url") or item.get("metadata", {}).get("url") or "")
                description = str(item.get("description") or item.get("snippet") or "").strip()
                markdown = str(item.get("markdown") or "").strip()

                lines.append(f"{idx}. {title}")
                if url:
                    lines.append(f"   URL: {url}")
                if description:
                    lines.append(f"   Summary: {description}")
                if markdown:
                    excerpt = _truncate_text(markdown, 2200)
                    lines.append("   Content:")
                    lines.append("   " + excerpt.replace("\n", "\n   "))

            if not items:
                lines.append("No results returned.")
            if errors:
                lines.append("")
                lines.extend(f"Fallback note: {error}" for error in errors)

            return ToolResult(
                success=True,
                content="\n".join(lines),
                metadata={"backend": "firecrawl", "response": response},
            )
        except Exception:
            errors.append("fallback web search provider failed")
            return ToolResult(success=False, content="", error="; ".join(errors))

    def validate_parameters(  # type: ignore[override]
        self,
        query: str,
        limit: int = 5,
        backend: str = "auto",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        if not query.strip():
            raise ToolValidationError("query must not be empty")
        if backend not in {"auto", "exa", "firecrawl"}:
            raise ToolValidationError("backend must be one of: auto, exa, firecrawl")
        if not 1 <= int(limit) <= 10:
            raise ToolValidationError("limit must be between 1 and 10")
        if include_domains and exclude_domains:
            raise ToolValidationError("include_domains and exclude_domains cannot be used together")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to run against the public web.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Maximum number of results to return.",
                    "default": 5,
                },
                "fetch_content": {
                    "type": "boolean",
                    "description": "Whether to include fetched page content for the results.",
                    "default": False,
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional domain allowlist, for example ['docs.python.org'].",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional domain blocklist, for example ['wikipedia.org'].",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }


class WebFetchTool(BaseTool):
    """Fetch live webpage content."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch and read a public web page as cleaned text or markdown. Use this after a search "
            "result or when the user gives you a URL to read."
        )

    def execute(  # type: ignore[override]
        self,
        url: str,
        backend: str = "auto",
        max_chars: int = 12000,
        only_main_content: bool = True,
    ) -> ToolResult:
        self.validate_parameters(url=url, backend=backend, max_chars=max_chars)
        errors: list[str] = []

        if backend in {"auto", "exa"}:
            for exa_args in ({"urls": [url]}, {"url": url}):
                try:
                    exa_response = _call_exa_tool("web_fetch_exa", exa_args)
                    text = _render_mcp_text_response(f"Fetched page: {url}", exa_response)
                    return ToolResult(
                        success=True,
                        content=_truncate_text(text, max_chars),
                        metadata={"backend": "exa", "response": exa_response},
                    )
                except Exception:
                    pass
            if backend == "exa":
                return ToolResult(success=False, content="", error="web fetch provider failed")
            errors.append("primary web fetch provider failed")

        try:
            response = _firecrawl_scrape(
                {
                    "url": url,
                    "formats": ["markdown"],
                    "onlyMainContent": only_main_content,
                }
            )
            data = response.get("data", {}) or {}
            title = str(data.get("metadata", {}).get("title") or "Untitled")
            markdown = str(data.get("markdown") or "").strip()

            lines = [
                f"Fetched page: {url}",
                f"Title: {title}",
                "",
                _truncate_text(markdown, max_chars),
            ]
            if errors:
                lines.append("")
                lines.extend(f"Fallback note: {error}" for error in errors)

            return ToolResult(
                success=True,
                content="\n".join(lines).strip(),
                metadata={"backend": "firecrawl", "response": response},
            )
        except Exception:
            errors.append("fallback web fetch provider failed")
            return ToolResult(success=False, content="", error="; ".join(errors))

    def validate_parameters(  # type: ignore[override]
        self,
        url: str,
        backend: str = "auto",
        max_chars: int = 12000,
        **kwargs: Any,
    ) -> None:
        if not url.startswith(("http://", "https://")):
            raise ToolValidationError("url must start with http:// or https://")
        if backend not in {"auto", "exa", "firecrawl"}:
            raise ToolValidationError("backend must be one of: auto, exa, firecrawl")
        if not 1000 <= int(max_chars) <= 50000:
            raise ToolValidationError("max_chars must be between 1000 and 50000")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Public web URL to fetch and read.",
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 50000,
                    "description": "Maximum number of characters to return from the fetched page.",
                    "default": 12000,
                },
                "only_main_content": {
                    "type": "boolean",
                    "description": "Whether to strip navigation and other page chrome when supported.",
                    "default": True,
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        }


# Built-in tools
class ReadFileTool(BaseTool):
    """Tool for reading files with slice and indentation-aware modes.

    Supports two modes:
    - slice (default): Read specific line ranges
    - indentation: Intelligently expand around an anchor line based on code structure
    """

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return """Read a text file from the local workspace.

Modes:
- slice (default): Read specific line ranges. Use 'ranges' parameter.
- indentation: Intelligently read a code block around an anchor line.
  Automatically captures the surrounding context (function, class, etc.).
  Use 'offset', 'anchor_line', 'max_levels' parameters.

Use relative paths from current working directory."""

    def execute(  # type: ignore[override]
        self,
        path: str,
        # Slice mode parameters
        ranges: list[str] | None = None,
        max_lines: int | None = None,
        # Mode selection
        mode: str = "slice",
        # Indentation mode parameters
        offset: int = 1,
        limit: int = 200,
        anchor_line: int | None = None,
        max_levels: int = 2,
        include_siblings: bool = False,
        include_header: bool = True,
    ) -> ToolResult:
        """Execute the read file tool.

        Args:
            path: Path to file
            ranges: Line ranges for slice mode (e.g., ["1-100", "200-250"])
            max_lines: Maximum lines to return per block
            mode: "slice" or "indentation"
            offset: Starting line for indentation mode (1-indexed)
            limit: Max lines to return in indentation mode
            anchor_line: Center line for indentation expansion (defaults to offset)
            max_levels: How many parent indentation levels to include (0=unlimited)
            include_siblings: Include blocks at same indentation level
            include_header: Include comments/decorators above the block
        """
        from pathlib import Path

        try:
            file_path = Path(path).expanduser().resolve()

            if not file_path.exists():
                return ToolResult(success=False, content="", error=f"File not found: {file_path}")

            if not file_path.is_file():
                return ToolResult(success=False, content="", error=f"Path is a directory, not a file: {file_path}")

            if mode == "indentation":
                return self._read_indentation_mode(
                    file_path,
                    offset=offset,
                    limit=limit,
                    anchor_line=anchor_line,
                    max_levels=max_levels,
                    include_siblings=include_siblings,
                    include_header=include_header,
                    max_lines=max_lines,
                )
            else:
                return self._read_slice_mode(file_path, ranges, max_lines)

        except Exception as e:
            return ToolResult(success=False, content="", error=f"Failed to read file: {type(e).__name__}: {e}")

    def _read_slice_mode(self, file_path: Path, ranges: list[str] | None, max_lines: int | None) -> ToolResult:
        """Read file using slice mode (line ranges)."""
        from .readfile import read_file_with_ranges

        blocks = read_file_with_ranges(file_path, ranges or [])

        content_parts = []
        for block in blocks:
            header = f"{file_path}:{block['start']}-{block['end']}"
            content_parts.append(f"**{header}**")

            for lineno, line in block["lines"][: max_lines or 400]:
                content_parts.append(f"{lineno:>6} | {line}")

            if len(block["lines"]) > (max_lines or 400):
                content_parts.append("... (truncated)")

        content = "\n".join(content_parts)

        return ToolResult(
            success=True,
            content=content,
            metadata={
                "file_path": str(file_path),
                "mode": "slice",
                "blocks_read": len(blocks),
                "total_lines": sum(len(block["lines"]) for block in blocks),
            },
        )

    def _read_indentation_mode(
        self,
        file_path: Path,
        offset: int,
        limit: int,
        anchor_line: int | None,
        max_levels: int,
        include_siblings: bool,
        include_header: bool,
        max_lines: int | None,
    ) -> ToolResult:
        """Read file using indentation-aware mode."""
        from .readfile import IndentationOptions, read_file_with_indentation

        options = IndentationOptions(
            anchor_line=anchor_line,
            max_levels=max_levels,
            include_siblings=include_siblings,
            include_header=include_header,
            max_lines=max_lines,
        )

        blocks = read_file_with_indentation(file_path, offset, limit, options)

        content_parts = []
        for block in blocks:
            anchor_info = f" (anchor: L{block.get('anchor', offset)})" if block.get("anchor") else ""
            header = f"{file_path}:{block['start']}-{block['end']}{anchor_info}"
            content_parts.append(f"**{header}** [indentation mode]")

            for lineno, line in block["lines"]:
                content_parts.append(f"L{lineno}: {line}")

        content = "\n".join(content_parts)

        return ToolResult(
            success=True,
            content=content,
            metadata={
                "file_path": str(file_path),
                "mode": "indentation",
                "anchor_line": anchor_line or offset,
                "blocks_read": len(blocks),
                "total_lines": sum(len(block["lines"]) for block in blocks),
            },
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative to current working directory)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["slice", "indentation"],
                    "description": "Reading mode: 'slice' for line ranges, 'indentation' for smart block reading",
                },
                # Slice mode
                "ranges": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "[Slice mode] Line ranges like '1-200'",
                },
                "max_lines": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5000,
                    "description": "Maximum lines to return per block (default 400 for slice, 200 for indentation)",
                },
                # Indentation mode
                "offset": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "[Indentation mode] Starting line number (1-indexed)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2000,
                    "description": "[Indentation mode] Maximum lines to return (default 200)",
                },
                "anchor_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "[Indentation mode] Center line for expansion (defaults to offset)",
                },
                "max_levels": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "[Indentation mode] Parent indent levels to include. 0=unlimited, 1=immediate parent, etc.",
                },
                "include_siblings": {
                    "type": "boolean",
                    "description": "[Indentation mode] Include sibling blocks at same indentation",
                },
                "include_header": {
                    "type": "boolean",
                    "description": "[Indentation mode] Include comments/decorators above the block",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        }


class ThinkTool(BaseTool):
    """Tool for internal reasoning and planning."""

    @property
    def name(self) -> str:
        return "think"

    @property
    def description(self) -> str:
        return "Use this tool for internal reasoning, planning, and organizing your thoughts before taking action."

    def execute(self, thought: str) -> ToolResult:  # type: ignore[override]
        """Execute thinking process."""
        return ToolResult(success=True, content=f"🤔 Thinking: {thought}", metadata={"thought": thought})

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"thought": {"type": "string", "description": "Your thoughts, plans, or reasoning"}},
            "required": ["thought"],
            "additionalProperties": False,
        }


class BashTool(BaseTool):
    """Tool for executing bash commands."""

    MAX_OUTPUT_CHARS = 6000

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute bash commands. Use for file operations, running scripts, or system commands. "
            "Output is truncated; for large files prefer rg/head/tail/sed ranges instead of cat."
        )

    def execute(self, command: str, timeout: int = 30, cwd: str | None = None) -> ToolResult:  # type: ignore[override]
        """Execute bash command."""
        import subprocess

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )

            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            output = output or "(no output)"
            original_output_length = len(output)
            truncated = original_output_length > self.MAX_OUTPUT_CHARS
            if truncated:
                output = _truncate_text(output, self.MAX_OUTPUT_CHARS)

            return ToolResult(
                success=result.returncode == 0,
                content=output,
                metadata={
                    "command": command,
                    "exit_code": result.returncode,
                    "cwd": cwd,
                    "truncated": truncated,
                    "original_output_length": original_output_length,
                },
                error=None if result.returncode == 0 else f"Command exited with code {result.returncode}",
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error=f"Command timed out after {timeout} seconds")
        except Exception as e:
            return ToolResult(success=False, content="", error=f"Command failed: {type(e).__name__}: {e}")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Bash command to execute"},
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 600,
                    "description": "Timeout in seconds (default: 30)",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        }


class GrepTool(BaseTool):
    """Tool for searching files using ripgrep."""

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search for patterns in files using ripgrep. Returns matching lines with file paths and line numbers."

    def execute(  # type: ignore[override]
        self,
        pattern: str,
        paths: list[str] | None = None,
        ignore_case: bool = False,
        hidden: bool = False,
        context: int = 0,
        globs: list[str] | None = None,
    ) -> ToolResult:
        """Execute grep search."""
        import shutil
        import subprocess

        if shutil.which("rg") is None:
            return ToolResult(
                success=False, content="", error="ripgrep (rg) not found on PATH. Please install ripgrep."
            )

        try:
            cmd = ["rg", pattern, *(paths or ["."]), "-n"]
            if ignore_case:
                cmd.append("-i")
            if hidden:
                cmd.append("--hidden")
            if context:
                cmd.extend(["-C", str(context)])
            for g in globs or []:
                cmd.extend(["-g", g])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                return ToolResult(
                    success=True,
                    content=result.stdout,
                    metadata={
                        "pattern": pattern,
                        "paths": paths or ["."],
                        "match_count": len(result.stdout.splitlines()),
                    },
                )
            elif result.returncode == 1:
                # No matches found
                return ToolResult(
                    success=True, content="No matches found.", metadata={"pattern": pattern, "match_count": 0}
                )
            else:
                return ToolResult(
                    success=False,
                    content=result.stdout,
                    error=result.stderr or f"ripgrep exited with code {result.returncode}",
                )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error="Search timed out after 30 seconds")
        except Exception as e:
            return ToolResult(success=False, content="", error=f"Search failed: {type(e).__name__}: {e}")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Pattern to search for (regex supported)"},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Paths to search in (default: current directory)",
                },
                "ignore_case": {"type": "boolean", "description": "Case-insensitive search"},
                "hidden": {"type": "boolean", "description": "Search hidden files and directories"},
                "context": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Number of context lines to show around matches",
                },
                "globs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File glob patterns to filter (e.g., '*.py')",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }


class WriteFileTool(BaseTool):
    """Tool for writing content to files."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file. Creates new file or overwrites existing file."

    def execute(self, path: str, content: str) -> ToolResult:  # type: ignore[override]
        """Execute the write file tool."""
        from pathlib import Path

        try:
            file_path = Path(path).expanduser().resolve()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

            return ToolResult(
                success=True,
                content=f"Successfully wrote {len(content)} characters to {file_path}",
                metadata={"file_path": str(file_path), "size": len(content)},
            )
        except Exception as e:
            return ToolResult(success=False, content="", error=f"Failed to write file: {type(e).__name__}: {e}")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }


class ApplyPatchTool(BaseTool):
    """Tool for applying diff-based patches to files.

    This tool provides a more efficient and precise way to edit files compared
    to write_file. It uses a structured patch format that:
    - Minimizes token usage (only sends diffs, not full files)
    - Uses context anchors for precise location matching
    - Supports batch operations (multiple files in one patch)
    - Provides atomic file operations (add, delete, update, rename)
    """

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return """Apply diff-based patches to files. More efficient than write_file for edits.

Patch Format:
*** Begin Patch
*** Add File: path/to/new.py
+line 1
+line 2

*** Update File: path/to/existing.py
@@ class ClassName
@@ def method_name():
 context line (space prefix)
-line to delete (minus prefix)
+line to add (plus prefix)
 more context

*** Delete File: path/to/obsolete.py
*** End Patch

Key features:
- Use @@ anchors to locate the right position (class names, function signatures)
- Include 3 lines of context before and after changes
- Prefix context lines with space, deletions with -, additions with +
- All paths must be relative (never absolute)

Example for fixing a bug:
*** Begin Patch
*** Update File: src/calculator.py
@@ def subtract(a, b):
     \"\"\"Subtract b from a.\"\"\"
-    return a + b
+    return a - b
*** End Patch"""

    def execute(self, patch: str) -> ToolResult:  # type: ignore[override]
        """Execute the apply patch tool.

        Args:
            patch: The patch content in the apply_patch format
        """
        from pathlib import Path

        from .apply_patch import PatchApplyError, PatchParseError, apply_patch_text

        try:
            changes = apply_patch_text(patch, Path.cwd())

            if not changes:
                return ToolResult(
                    success=True,
                    content="Patch applied but no changes were made.",
                    metadata={"changes": []},
                )

            # Format summary
            summary_parts = ["Patch applied successfully:"]
            total_additions = 0
            total_deletions = 0

            for change in changes:
                if change["type"] == "add":
                    summary_parts.append(f"  + Created: {change['path']} ({change['lines_added']} lines)")
                    total_additions += change["lines_added"]
                elif change["type"] == "delete":
                    summary_parts.append(f"  - Deleted: {change['path']}")
                elif change["type"] == "update":
                    additions = change.get("additions", 0)
                    deletions = change.get("deletions", 0)
                    target = change.get("target_path")
                    if target and target != change["path"]:
                        summary_parts.append(f"  ~ Updated: {change['path']} -> {target} (+{additions}/-{deletions})")
                    else:
                        summary_parts.append(f"  ~ Updated: {change['path']} (+{additions}/-{deletions})")
                    total_additions += additions
                    total_deletions += deletions

            summary_parts.append(f"\nTotal: +{total_additions}/-{total_deletions} lines")

            return ToolResult(
                success=True,
                content="\n".join(summary_parts),
                metadata={
                    "changes": changes,
                    "total_additions": total_additions,
                    "total_deletions": total_deletions,
                },
            )

        except PatchParseError as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Patch parse error: {e}. Check the patch format.",
            )
        except PatchApplyError as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Patch apply error: {e}. The file may have been modified.",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to apply patch: {type(e).__name__}: {e}",
            )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": (
                        "The patch content. Must start with '*** Begin Patch' and end with "
                        "'*** End Patch'. Use '*** Add File:', '*** Update File:', or "
                        "'*** Delete File:' for operations. In hunks, prefix context lines "
                        "with space, deletions with -, additions with +."
                    ),
                },
            },
            "required": ["patch"],
            "additionalProperties": False,
        }


class TodoTool(BaseTool):
    """Tool for managing a todo list to track tasks."""

    # Shared state across all instances — protected by a class-level lock
    _todos: list[dict[str, str]] = []
    _lock: threading.Lock = threading.Lock()

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return (
            "Manage a todo list to track tasks. Use action='read' to view current todos, "
            "action='write' with a complete list to update. Helps organize complex multi-step tasks."
        )

    def execute(self, action: str, todos: list[dict[str, str]] | None = None) -> ToolResult:  # type: ignore[override]
        """Execute todo operations."""
        if action == "read":
            return self._read_todos()
        elif action == "write":
            return self._write_todos(todos or [])
        else:
            return ToolResult(success=False, content="", error=f"Invalid action '{action}'. Use 'read' or 'write'.")

    def _read_todos(self) -> ToolResult:
        with TodoTool._lock:
            todos = list(TodoTool._todos)

        if not todos:
            return ToolResult(success=True, content="No todos.", metadata={"count": 0})

        lines = ["## Todo List", ""]
        for todo in todos:
            status = todo.get("status", "pending")
            content = todo.get("content", "")
            tid = todo.get("id", "")
            icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "cancelled": "❌"}.get(status, "⬜")
            lines.append(f"{icon} [{tid}] {content} ({status})")

        return ToolResult(success=True, content="\n".join(lines), metadata={"count": len(todos)})

    def _write_todos(self, todos: list[dict[str, str]]) -> ToolResult:
        # Validate todos
        valid_statuses = {"pending", "in_progress", "completed", "cancelled"}
        for i, todo in enumerate(todos):
            if "id" not in todo or "content" not in todo:
                return ToolResult(success=False, content="", error=f"Todo {i} missing 'id' or 'content'")
            if todo.get("status", "pending") not in valid_statuses:
                return ToolResult(success=False, content="", error=f"Invalid status for todo {todo['id']}")

        # Check unique IDs
        ids = [t["id"] for t in todos]
        if len(ids) != len(set(ids)):
            return ToolResult(success=False, content="", error="Todo IDs must be unique")

        with TodoTool._lock:
            TodoTool._todos = todos
        return ToolResult(
            success=True,
            content=f"Updated {len(todos)} todos.",
            metadata={"count": len(todos)},
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write"],
                    "description": "Action to perform: 'read' to view todos, 'write' to update the list",
                },
                "todos": {
                    "type": "array",
                    "description": "Complete list of todos (required for 'write' action)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique identifier for the todo"},
                            "content": {"type": "string", "description": "Description of the task"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "description": "Status of the todo (default: pending)",
                            },
                        },
                        "required": ["id", "content"],
                    },
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }


class ParallelTaskTool(BaseTool):
    """Tool for spawning parallel sub-agent tasks.

    This tool allows the agent to delegate work to sub-agents that execute
    tasks in parallel, enabling more efficient handling of complex requests.
    """

    def __init__(self, session_id: str | None = None):
        super().__init__()
        self.session_id = session_id

    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        return """Spawn and manage parallel sub-agent tasks.

This tool allows you to delegate work to specialized sub-agents that
run in parallel. Use this for:
- Exploring multiple files simultaneously
- Running analysis while continuing other work
- Breaking complex tasks into smaller parallel pieces

Actions:
- create: Create a new task for a sub-agent to execute
- status: Check the status of a task
- wait: Wait for a task to complete and get results
- cancel: Cancel a running task
- list: List all tasks

Agent Types:
- explorer: Fast read-only codebase exploration (50 steps max)
- planner: Analysis and planning (30 steps max)
- focused_coder: Specific implementation tasks (100 steps max)

Examples:
  Create: {"action": "create", "description": "Find all TODO comments", "agent_type": "explorer"}
  Check:  {"action": "status", "task_id": "abc123"}
  Wait:   {"action": "wait", "task_id": "abc123", "timeout": 60}
  List:   {"action": "list"}
"""

    def execute(  # type: ignore[override]
        self,
        action: str,
        description: str | None = None,
        agent_type: str = "focused_coder",
        task_id: str | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Execute the task tool."""
        import asyncio

        from .task import TaskTool

        tool = TaskTool(session_id=self.session_id)

        async def run_task():
            return await tool.execute(
                action=action,
                description=description,
                agent_type=agent_type,
                task_id=task_id,
                timeout=timeout,
            )

        try:
            # Check if we're already in an async context
            try:
                asyncio.get_running_loop()
                # We're in an async context, create a task and wait
                # Use nest_asyncio if available, otherwise use a different approach
                try:
                    import nest_asyncio  # type: ignore[import-not-found]

                    nest_asyncio.apply()
                    result = asyncio.run(run_task())
                except ImportError:
                    # Create task and get result via future
                    future = asyncio.ensure_future(run_task())
                    # We can't block here, so return a message about the task
                    if action == "create":
                        # For create action, we can run it synchronously
                        # by creating a new thread
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, run_task())
                            result = future.result(timeout=30)
                    else:
                        # For other actions, try to run in the current loop
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, run_task())
                            result = future.result(timeout=timeout or 30)
            except RuntimeError:
                # No running loop, safe to use asyncio.run
                result = asyncio.run(run_task())

            return ToolResult(success=True, content=result)
        except Exception as e:
            return ToolResult(success=False, content="", error=str(e))

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "status", "wait", "cancel", "list"],
                    "description": "Action to perform",
                },
                "description": {
                    "type": "string",
                    "description": "Task description (required for 'create' action)",
                },
                "agent_type": {
                    "type": "string",
                    "enum": ["explorer", "planner", "focused_coder"],
                    "description": "Type of agent for the task (default: focused_coder)",
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID (required for status/wait/cancel actions)",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds for wait action",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }


class MemoryTool(BaseTool):
    """Tool for reading and writing persistent agent memory.

    Provides access to the two-layer memory system:
    - Long-term memory (MEMORY.md): Curated facts and knowledge
    - History log (HISTORY.md): Append-only searchable activity log
    """

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return """Manage persistent memory across sessions.

Actions:
- read: Read long-term memory (MEMORY.md) for the given scope
- write: Update long-term memory (overwrites). Keep it organized and compact.
- append: Add an entry to the history log (HISTORY.md + SQLite events)
- search: Search all memory layers (MEMORY.md, facts, events) using FTS5
- stats: Get memory statistics
- read_soul: Read the durable soul/persona (SOUL.md)
- write_soul: Update the durable global soul/persona (SOUL.md)
- read_identity: Read the durable identity profile (IDENTITY.md)
- write_identity: Update the durable global identity profile (IDENTITY.md)
- identify: Read identity, or update it when content is provided
- upsert_fact: Save a fact (key-value with category) to declarative memory
- get_fact: Get a specific fact by key
- list_facts: List facts, optionally filtered by category
- delete_fact: Delete a fact by key

Scopes:
- user: Global memory (~/.config/amcp/memory/)
- project: Project-specific memory (.amcp/memory/)

Identity and soul are global-only for prompt injection. Use scope="user" for
identify, write_identity, and write_soul; project scope is for project facts and
history, not agent persona.

Use this tool to:
- Remember important patterns, preferences, and project context
- Log significant decisions and learnings
- Store and retrieve structured facts and knowledge
- Search past activities and knowledge with full-text search

Examples:
  Read: {"action": "read", "scope": "project"}
  Write: {"action": "write", "content": "# Project Notes\\n- Uses Python 3.12", "scope": "project"}
  Append: {"action": "append", "content": "Discovered auth module needs refactoring", "tags": ["discovery"]}
  Search: {"action": "search", "query": "auth module"}
  Set soul: {"action": "write_soul", "content": "You are a careful pair programmer.", "scope": "user"}
  Identify: {"action": "identify", "content": "Name: AMCP\\nRole: long-running coding agent", "scope": "user"}
  Upsert fact: {"action": "upsert_fact", "key": "python_version", "content": "3.12", "category": "config"}
  Get fact: {"action": "get_fact", "key": "python_version"}
  List facts: {"action": "list_facts", "category": "config"}
  Delete fact: {"action": "delete_fact", "key": "python_version"}
"""

    def execute(  # type: ignore[override]
        self,
        action: str,
        content: str | None = None,
        scope: str = "user",
        query: str | None = None,
        tags: list[str] | None = None,
        max_results: int = 20,
        key: str | None = None,
        category: str | None = None,
        project_root: str | None = None,
    ) -> ToolResult:
        """Execute memory operations."""
        from .memory import get_memory_manager

        try:
            manager = get_memory_manager(Path(project_root) if project_root else None)

            def _read() -> ToolResult:
                memory_content = manager.read_long_term(scope)
                if not memory_content:
                    return ToolResult(
                        success=True,
                        content=f"No long-term memory found for scope '{scope}'.",
                        metadata={"scope": scope},
                    )
                return ToolResult(
                    success=True,
                    content=memory_content,
                    metadata={"scope": scope, "size": len(memory_content)},
                )

            def _write() -> ToolResult:
                if not content:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Content is required for write action.",
                    )
                manager.write_long_term(content, scope)
                return ToolResult(
                    success=True,
                    content=(f"Long-term memory updated ({len(content)} chars) in scope '{scope}'."),
                    metadata={"scope": scope, "size": len(content)},
                )

            def _append() -> ToolResult:
                if not content:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Content is required for append action.",
                    )
                manager.append_history(content, session_id="agent", tags=tags, scope=scope)
                return ToolResult(
                    success=True,
                    content="Entry appended to history log.",
                    metadata={"scope": scope, "tags": tags or []},
                )

            def _search() -> ToolResult:
                if not query:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Query is required for search action.",
                    )
                results = manager.search(query, max_results=max_results)
                if not results:
                    return ToolResult(
                        success=True,
                        content=f"No results found for '{query}'.",
                        metadata={"query": query, "count": 0},
                    )
                lines = [f"Found {len(results)} results for '{query}':"]
                for r in results:
                    lines.append(f"  [{r.source}:L{r.line_number}] {r.content}")
                return ToolResult(
                    success=True,
                    content="\n".join(lines),
                    metadata={"query": query, "count": len(results)},
                )

            def _stats() -> ToolResult:
                stats = manager.get_stats()
                lines = ["Memory Statistics:"]
                for scope_name, scope_stats in stats.items():
                    lines.append(f"  {scope_name}:")
                    for k, v in scope_stats.items():
                        lines.append(f"    {k}: {v}")
                return ToolResult(
                    success=True,
                    content="\n".join(lines),
                    metadata=stats,
                )

            def _read_soul() -> ToolResult:
                soul = manager.read_soul(scope, include_default=True)
                source = "custom" if manager.read_soul(scope) else "default"
                return ToolResult(
                    success=True,
                    content=soul,
                    metadata={"scope": scope, "source": source, "size": len(soul)},
                )

            def _write_soul() -> ToolResult:
                if content is None:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Content is required for write_soul action.",
                    )
                manager.write_soul(content, scope)
                return ToolResult(
                    success=True,
                    content=f"Soul updated ({len(content)} chars) in scope '{scope}'.",
                    metadata={"scope": scope, "size": len(content)},
                )

            def _read_identity() -> ToolResult:
                identity = manager.read_identity(scope)
                if not identity:
                    return ToolResult(
                        success=True,
                        content=f"No identity profile found for scope '{scope}'.",
                        metadata={"scope": scope, "size": 0},
                    )
                return ToolResult(
                    success=True,
                    content=identity,
                    metadata={"scope": scope, "size": len(identity)},
                )

            def _write_identity() -> ToolResult:
                if content is None:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Content is required for write_identity action.",
                    )
                manager.write_identity(content, scope)
                return ToolResult(
                    success=True,
                    content=f"Identity updated ({len(content)} chars) in scope '{scope}'.",
                    metadata={"scope": scope, "size": len(content)},
                )

            def _identify() -> ToolResult:
                if content is not None:
                    return _write_identity()
                return _read_identity()

            def _upsert_fact() -> ToolResult:
                if not key:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Key is required for upsert_fact action.",
                    )
                if not content:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Content is required for upsert_fact action.",
                    )
                manager.upsert_fact(
                    key=key,
                    value=content,
                    category=category or "general",
                    scope=scope,
                )
                return ToolResult(
                    success=True,
                    content=f"Fact '{key}' saved in scope '{scope}'.",
                    metadata={"key": key, "scope": scope},
                )

            def _get_fact() -> ToolResult:
                if not key:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Key is required for get_fact action.",
                    )
                fact = manager.get_fact(key, scope=scope)
                if not fact:
                    return ToolResult(
                        success=True,
                        content=f"No fact found for key '{key}'.",
                        metadata={"key": key, "scope": scope},
                    )
                lines = [
                    f"Fact: {fact['key']}",
                    f"  Value: {fact['value']}",
                    f"  Category: {fact['category']}",
                    f"  Confidence: {fact['confidence']}",
                    f"  Updated: {fact['updated_at']}",
                ]
                return ToolResult(
                    success=True,
                    content="\n".join(lines),
                    metadata=fact,
                )

            def _list_facts() -> ToolResult:
                facts = manager.list_facts(category=category, scope=scope)
                if not facts:
                    cat_msg = f" in category '{category}'" if category else ""
                    return ToolResult(
                        success=True,
                        content=f"No facts found{cat_msg}.",
                        metadata={"count": 0},
                    )
                lines = [f"Found {len(facts)} facts:"]
                for f in facts:
                    lines.append(f"  [{f['category']}] {f['key']}: {f['value']}")
                return ToolResult(
                    success=True,
                    content="\n".join(lines),
                    metadata={"count": len(facts)},
                )

            def _delete_fact() -> ToolResult:
                if not key:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Key is required for delete_fact action.",
                    )
                deleted = manager.delete_fact(key, scope=scope)
                if deleted:
                    return ToolResult(
                        success=True,
                        content=f"Fact '{key}' deleted.",
                        metadata={"key": key, "scope": scope},
                    )
                return ToolResult(
                    success=True,
                    content=f"No fact found for key '{key}'.",
                    metadata={"key": key, "scope": scope},
                )

            handlers: dict[str, Callable[[], ToolResult]] = {
                "read": _read,
                "write": _write,
                "append": _append,
                "search": _search,
                "stats": _stats,
                "read_soul": _read_soul,
                "write_soul": _write_soul,
                "read_identity": _read_identity,
                "write_identity": _write_identity,
                "identify": _identify,
                "upsert_fact": _upsert_fact,
                "get_fact": _get_fact,
                "list_facts": _list_facts,
                "delete_fact": _delete_fact,
            }

            if action not in handlers:
                valid = ", ".join(handlers.keys())
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Invalid action '{action}'. Use: {valid}",
                )

            persona_actions = {
                "read_soul",
                "write_soul",
                "read_identity",
                "write_identity",
                "identify",
            }
            if action in persona_actions and scope != "user":
                return ToolResult(
                    success=False,
                    content="",
                    error=(
                        "Agent identity and soul are global-only. Use scope='user' for "
                        f"action '{action}'; project scope is only for project memory."
                    ),
                )

            return handlers[action]()

        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Memory operation failed: {e}",
            )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "read",
                        "write",
                        "append",
                        "search",
                        "stats",
                        "read_soul",
                        "write_soul",
                        "read_identity",
                        "write_identity",
                        "identify",
                        "upsert_fact",
                        "get_fact",
                        "list_facts",
                        "delete_fact",
                    ],
                    "description": "Action to perform",
                },
                "content": {
                    "type": "string",
                    "description": ("Content for write/append actions, or value for upsert_fact"),
                },
                "scope": {
                    "type": "string",
                    "enum": ["user", "project"],
                    "description": (
                        "Memory scope (default: user). Identity and soul actions are "
                        "global-only for prompt injection; use user for identify, "
                        "write_identity, and write_soul."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for search action)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": ("Tags for history entries (for append action)"),
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum search results (default: 20)",
                },
                "key": {
                    "type": "string",
                    "description": ("Fact key (for upsert_fact, get_fact, delete_fact actions)"),
                },
                "category": {
                    "type": "string",
                    "description": ("Fact category (for upsert_fact, list_facts)"),
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }


class SessionSearchTool(BaseTool):
    """Tool for searching persisted user/assistant session transcripts."""

    @property
    def name(self) -> str:
        return "session_search"

    @property
    def description(self) -> str:
        return """Search prior AMCP conversation transcripts.

Use this proactively before asking the user to repeat prior work, plans,
completed tasks, decisions, dates, preferences, or follow-ups. Transcript
search is for episodic task history; use memory for curated durable facts."""

    def execute(  # type: ignore[override]
        self,
        query: str,
        max_results: int = 10,
        session_id: str | None = None,
        source: str | None = None,
    ) -> ToolResult:
        """Search session transcripts."""
        if not query.strip():
            return ToolResult(success=False, content="", error="Query is required.")
        try:
            from .session_search import get_transcript_store

            results = get_transcript_store().search(
                query,
                max_results=max_results,
                session_id=session_id,
                source=source,
            )
        except Exception as e:
            return ToolResult(success=False, content="", error=f"Session search failed: {e}")

        if not results:
            return ToolResult(
                success=True,
                content=f"No transcript results found for '{query}'.",
                metadata={"query": query, "count": 0},
            )

        lines = [f"Found {len(results)} transcript results for '{query}':"]
        for idx, result in enumerate(results, start=1):
            chat = f" chat:{result.chat_id}" if result.chat_id else ""
            lines.append(
                f"{idx}. [{result.timestamp} session:{result.session_id}"
                f" {result.source}{chat} {result.role}] {result.snippet}"
            )
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={"query": query, "count": len(results)},
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for prior session transcripts.",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum results to return (default: 10).",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional session id filter.",
                },
                "source": {
                    "type": "string",
                    "description": "Optional source filter, such as telegram or agent.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }


# Initialize default tool registry
def create_default_tool_registry(
    enable_write: bool = True,
    enable_apply_patch: bool = True,
    enable_task: bool = True,
    session_id: str | None = None,
) -> ToolRegistry:
    """Create a tool registry with default tools.

    Args:
        enable_write: Enable write_file tool
        enable_apply_patch: Enable apply_patch tool (recommended for file edits)
        enable_task: Enable task tool for parallel sub-agents
        session_id: Session ID for task tool
    """
    registry = ToolRegistry()

    # Register built-in tools
    registry.register(ReadFileTool())
    registry.register(GrepTool())
    registry.register(ThinkTool())
    registry.register(BashTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(TodoTool())
    registry.register(MemoryTool())
    registry.register(SessionSearchTool())

    if enable_write:
        registry.register(WriteFileTool())
    if enable_apply_patch:
        registry.register(ApplyPatchTool())
    if enable_task:
        registry.register(ParallelTaskTool(session_id=session_id))

    return registry


# Global tool registry instance — protected by a lock for thread-safe lazy init
_default_registry: ToolRegistry | None = None
_registry_lock: threading.Lock = threading.Lock()


def get_tool_registry(enable_write: bool | None = None) -> ToolRegistry:
    """Get the global tool registry instance."""
    global _default_registry
    if _default_registry is None:
        with _registry_lock:
            # Double-checked locking pattern
            if _default_registry is None:
                # Load config to determine defaults
                from .config import load_config

                cfg = load_config()
                chat_cfg = cfg.chat

                # Use config values if not explicitly provided
                if enable_write is None:
                    enable_write = (
                        chat_cfg.write_tool_enabled if chat_cfg and chat_cfg.write_tool_enabled is not None else True
                    )

                _default_registry = create_default_tool_registry(enable_write=enable_write)
    return _default_registry


def register_tool(tool: BaseTool) -> None:
    """Register a tool with the global registry."""
    get_tool_registry().register(tool)
