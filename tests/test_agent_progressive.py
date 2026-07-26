from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from amcp.agent import Agent
from amcp.config import AMCPConfig, ChatConfig, ContextConfig, Server
from amcp.mcp_naming import is_mcp_tool_name, is_valid_function_name


@pytest.mark.asyncio
async def test_build_tools_progressive_filters_non_relevant(monkeypatch):
    cfg = AMCPConfig(
        servers={},
        chat=ChatConfig(model="unknown-model", mcp_tools_enabled=False),
        context=ContextConfig(
            progressive_tools=True,
            tool_relevance_threshold=0.95,
            min_prompt_budget=1800,
        ),
    )
    monkeypatch.setattr("amcp.agent.load_config", lambda: cfg)

    agent = Agent()
    tools, registry = await agent._build_tools_and_registry(
        user_input="hello",
        conversation_history=[{"role": "user", "content": "hello"}],
    )

    names = {tool["function"]["name"] for tool in tools}
    assert {"read_file", "grep", "think"}.issubset(names)
    assert "task" not in names
    assert registry == {}


@pytest.mark.asyncio
async def test_mcp_tools_are_exposed_under_provider_safe_names(monkeypatch):
    """MCP aliases must satisfy the strictest provider naming rule and stay reversible."""
    cfg = AMCPConfig(
        servers={"tavily": Server(url="https://mcp.example.com/mcp")},
        chat=ChatConfig(model="unknown-model", mcp_tools_enabled=True),
        context=ContextConfig(progressive_tools=False),
    )
    monkeypatch.setattr("amcp.agent.load_config", lambda: cfg)
    monkeypatch.setattr(
        "amcp.agent.list_mcp_tools",
        AsyncMock(
            return_value=[
                {"name": "tavily_search", "description": "search", "inputSchema": {"type": "object"}},
                {"name": "tavily.extract", "description": "extract", "inputSchema": {"type": "object"}},
                {"name": "tavily extract", "description": "extract again", "inputSchema": {"type": "object"}},
            ]
        ),
    )

    agent = Agent()
    tools, registry = await agent._build_tools_and_registry(user_input="search the web")

    names = [tool["function"]["name"] for tool in tools]
    assert all(is_valid_function_name(name) for name in names)
    assert not any("." in name for name in names)

    mcp_names = [name for name in names if is_mcp_tool_name(name)]
    assert mcp_names == [
        "mcp__tavily__tavily_search",
        "mcp__tavily__tavily_extract",
        "mcp__tavily__tavily_extract_2",
    ]
    # Aliases stay reversible so dispatch can reach the original MCP tool.
    assert registry == {
        "mcp__tavily__tavily_search": ("tavily", "tavily_search"),
        "mcp__tavily__tavily_extract": ("tavily", "tavily.extract"),
        "mcp__tavily__tavily_extract_2": ("tavily", "tavily extract"),
    }
