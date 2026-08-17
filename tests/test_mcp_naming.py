"""Tests for provider-safe tool function names."""

from __future__ import annotations

import pytest

from ankaloop.mcp_naming import (
    MAX_FUNCTION_NAME_LENGTH,
    MCP_TOOL_PREFIX,
    is_mcp_tool_name,
    is_valid_function_name,
    mcp_tool_name,
    sanitize_function_name,
    unique_function_name,
)


@pytest.mark.parametrize(
    "name",
    ["bash", "read_file", "mcp__tavily__tavily_search", "web-fetch", "a"],
)
def test_valid_function_names_are_accepted(name):
    assert is_valid_function_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "mcp.tavily.tavily_search",  # dots are rejected by Kimi/Moonshot
        "1tool",
        "_tool",
        "tool name",
        "tool:name",
        "工具",
        "a" * (MAX_FUNCTION_NAME_LENGTH + 1),
    ],
)
def test_invalid_function_names_are_rejected(name):
    assert not is_valid_function_name(name)


@pytest.mark.parametrize(
    "raw",
    [
        "mcp.tavily.tavily_search",
        "  spaced name  ",
        "9lives",
        "_leading",
        "tool:with/punctuation",
        "工具",
        "",
        "x" * 200,
    ],
)
def test_sanitize_always_returns_a_valid_name(raw):
    assert is_valid_function_name(sanitize_function_name(raw))


def test_sanitize_preserves_already_valid_names():
    assert sanitize_function_name("read_file") == "read_file"


def test_mcp_tool_name_uses_underscore_namespace():
    name = mcp_tool_name("tavily", "tavily_search")

    assert name == f"{MCP_TOOL_PREFIX}tavily__tavily_search"
    assert is_valid_function_name(name)
    assert is_mcp_tool_name(name)


@pytest.mark.parametrize(
    "server, tool",
    [
        ("my.server", "search.web"),
        ("weird server", "tool@v2"),
        ("s" * 60, "t" * 60),
    ],
)
def test_mcp_tool_name_sanitizes_untrusted_parts(server, tool):
    name = mcp_tool_name(server, tool)

    assert is_valid_function_name(name)
    assert is_mcp_tool_name(name)


def test_builtin_names_are_not_mistaken_for_mcp_tools():
    assert not is_mcp_tool_name("read_file")
    assert not is_mcp_tool_name("memory")


def test_unique_function_name_resolves_collisions():
    taken = {"mcp__a__tool"}

    first = unique_function_name("mcp__a__tool", taken)
    taken.add(first)
    second = unique_function_name("mcp__a__tool", taken)

    assert first == "mcp__a__tool_2"
    assert second == "mcp__a__tool_3"
    assert is_valid_function_name(first)


def test_unique_function_name_keeps_length_bound():
    base = mcp_tool_name("s" * 60, "t" * 60)

    candidate = unique_function_name(base, {base})

    assert candidate != base
    assert len(candidate) <= MAX_FUNCTION_NAME_LENGTH
    assert is_valid_function_name(candidate)
