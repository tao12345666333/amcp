from __future__ import annotations

import pytest

from amcp.agent import Agent
from amcp.config import AMCPConfig, ChatConfig, ContextConfig


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
