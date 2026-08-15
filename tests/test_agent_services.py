"""Focused coverage for the Stage 1 agent composition boundary."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amcp.agent import Agent, create_agent_by_name
from amcp.application_services import ApplicationServices
from amcp.config import AMCPConfig, ChatConfig, ContextConfig
from amcp.context_builder import ContextBuilder
from amcp.multi_agent import AgentRegistry
from amcp.server.config import ServerConfig
from amcp.server.session_manager import SessionManager
from amcp.tool_loop import ToolLoop
from amcp.tools import ToolRegistry
from amcp.turn_service import TurnService


def _services() -> ApplicationServices:
    return ApplicationServices(
        tool_registry=ToolRegistry(),
        agent_registry=AgentRegistry(),
        skill_manager=MagicMock(),
        transcript_store=MagicMock(),
        memory_manager_factory=MagicMock(),
    )


def test_agent_composes_stage_one_services(tmp_path):
    services = _services()
    with patch("amcp.agent.Path.home", return_value=tmp_path):
        agent = Agent(services=services)

    assert isinstance(agent.context_builder, ContextBuilder)
    assert isinstance(agent.tool_loop, ToolLoop)
    assert isinstance(agent.turn_service, TurnService)
    assert agent.tool_registry is services.tool_registry


@pytest.mark.asyncio
async def test_process_message_compatibility_entry_delegates(tmp_path):
    with patch("amcp.agent.Path.home", return_value=tmp_path):
        agent = Agent(services=_services())
    agent.turn_service.process_message = AsyncMock(return_value="done")  # type: ignore[method-assign]

    assert await agent._process_message("hello", tmp_path, False, False) == "done"
    agent.turn_service.process_message.assert_awaited_once_with("hello", tmp_path, False, False)


@pytest.mark.asyncio
async def test_context_and_tool_loop_compatibility_entries_delegate(tmp_path):
    with patch("amcp.agent.Path.home", return_value=tmp_path):
        agent = Agent(services=_services())
    agent.context_builder.build_tools_and_registry = AsyncMock(  # type: ignore[method-assign]
        return_value=([], {})
    )
    agent.tool_loop.enhanced_chat_with_tools = AsyncMock(  # type: ignore[method-assign]
        return_value="done"
    )

    assert await agent._build_tools_and_registry("hello") == ([], {})
    assert (
        await agent._enhanced_chat_with_tools(
            MagicMock(),
            [],
            [],
            {},
            False,
            MagicMock(),
        )
        == "done"
    )


@pytest.mark.asyncio
async def test_context_builder_uses_injected_tool_registry(tmp_path):
    services = _services()
    services.tool_registry.register_spec(
        {
            "type": "function",
            "function": {
                "name": "isolated_tool",
                "description": "Only available in this application",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    )
    config = AMCPConfig(
        servers={},
        chat=ChatConfig(mcp_tools_enabled=False),
        context=ContextConfig(progressive_tools=False),
    )
    with (
        patch("amcp.agent.Path.home", return_value=tmp_path),
        patch("amcp.agent.load_config", return_value=config),
    ):
        agent = Agent(services=services)
        tools, _ = await agent._build_tools_and_registry()

    assert [tool["function"]["name"] for tool in tools] == ["isolated_tool"]


def test_named_factory_uses_injected_agent_registry(tmp_path):
    services = _services()
    with (
        patch("amcp.agent.Path.home", return_value=tmp_path),
        patch("amcp.agent.get_agent_registry", side_effect=AssertionError("global registry used")),
    ):
        agent = create_agent_by_name("coder", services=services)

    assert agent.services is services


@pytest.mark.asyncio
async def test_session_manager_propagates_application_services(tmp_path):
    services = _services()
    manager = SessionManager(ServerConfig(work_dir=tmp_path), services)
    with patch("amcp.agent.Path.home", return_value=tmp_path):
        session = await manager.create_session(cwd=str(tmp_path))

    assert session.agent.services is services
    await session.agent.close()
