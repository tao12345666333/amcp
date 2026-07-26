"""Provider-safe function names for tools exposed to LLM backends.

Providers disagree on what a function name may contain. Gemini and GLM accept
dots, while Kimi/Moonshot rejects every name outside ``[A-Za-z][A-Za-z0-9_-]*``
with an HTTP 400 (``function name is invalid``). AMCP therefore exposes MCP
tools under the strictest common form (``mcp__<server>__<tool>``) and keeps the
original server/tool pair in the dispatch registry so the alias stays
reversible.
"""

from __future__ import annotations

import re
from collections.abc import Container

# Model-facing namespace for MCP tools.
MCP_TOOL_PREFIX = "mcp__"
MCP_NAME_SEPARATOR = "__"

# ``tool_tiers`` wildcard keys that apply to every MCP tool. The dotted key is
# the pre-``mcp__`` spelling and stays supported for existing configurations.
MCP_TOOL_TIER_KEY = "mcp__*"
LEGACY_MCP_TOOL_TIER_KEY = "mcp.*"

# OpenAI-compatible backends cap function names at 64 characters.
MAX_FUNCTION_NAME_LENGTH = 64

_VALID_FUNCTION_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_INVALID_FUNCTION_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def is_valid_function_name(name: str) -> bool:
    """Return whether a name is accepted by the strictest known provider."""
    if not name or len(name) > MAX_FUNCTION_NAME_LENGTH:
        return False
    return _VALID_FUNCTION_NAME.match(name) is not None


def sanitize_function_name(name: str, *, fallback: str = "tool") -> str:
    """Coerce an arbitrary name into a provider-safe function name.

    Args:
        name: Untrusted name, for example one reported by an MCP server.
        fallback: Prefix used when ``name`` cannot start a valid name on its
            own. It must already be a valid function name.

    Returns:
        A name matching ``[A-Za-z][A-Za-z0-9_-]*`` and no longer than
        ``MAX_FUNCTION_NAME_LENGTH``. Distinct inputs may collapse into the
        same output; use :func:`unique_function_name` to keep aliases unique.
    """
    cleaned = _INVALID_FUNCTION_NAME_CHARS.sub("_", name.strip())
    if not cleaned:
        cleaned = fallback
    elif not cleaned[0].isalpha():
        cleaned = f"{fallback}_{cleaned}"
    return cleaned[:MAX_FUNCTION_NAME_LENGTH]


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    """Build the provider-safe name that exposes one MCP tool to the model."""
    combined = f"{MCP_TOOL_PREFIX}{server_name.strip()}{MCP_NAME_SEPARATOR}{tool_name.strip()}"
    return sanitize_function_name(combined, fallback="mcp")


def is_mcp_tool_name(name: str) -> bool:
    """Return whether a model-facing tool name belongs to an MCP server."""
    return name.startswith(MCP_TOOL_PREFIX)


def unique_function_name(name: str, taken: Container[str]) -> str:
    """Return ``name``, or a numbered variant when the name is already taken."""
    if name not in taken:
        return name
    suffix = 2
    while True:
        marker = f"_{suffix}"
        candidate = f"{name[: MAX_FUNCTION_NAME_LENGTH - len(marker)]}{marker}"
        if candidate not in taken:
            return candidate
        suffix += 1
