"""Acceptance tests for execution boundaries."""

import asyncio
import json
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from amcp.agent import Agent
from amcp.agent_spec import ResolvedAgentSpec
from amcp.config import AMCPConfig, ContextConfig
from amcp.multi_agent import AgentMode
from amcp.tool_execution import (
    ToolCallProtocolError,
    ToolCapability,
    ToolExecutionContext,
    ToolExecutor,
    WorkspaceBoundaryError,
    normalize_tool_calls,
)
from amcp.tools import create_default_tool_registry


def _spec(*, tools=None, exclude_tools=None, can_delegate=True):
    return ResolvedAgentSpec(
        name="boundary",
        description="",
        mode=AgentMode.PRIMARY,
        system_prompt="",
        tools=tools,
        exclude_tools=exclude_tools or [],
        max_steps=5,
        model="",
        base_url="",
        can_delegate=can_delegate,
    )


def _executor(tmp_path, *, tools=None, exposed=None):
    return ToolExecutor(
        context=ToolExecutionContext("session", tmp_path, "turn"),
        capability=ToolCapability.from_spec(tools, [], True),
        exposed_tools=exposed or {"read_file", "write_file", "apply_patch", "bash"},
        registry=create_default_tool_registry(enable_task=False),
        mcp_registry={},
        config=AMCPConfig(servers={}, chat=None),
    )


def test_capability_distinguishes_inherit_deny_all_exclude_and_delegation():
    assert ToolCapability.from_spec(None, [], True).allows("bash")
    assert not ToolCapability.from_spec([], [], True).allows("bash")
    assert not ToolCapability.from_spec(None, ["bash"], True).allows("bash")
    assert not ToolCapability.from_spec(None, [], False).allows("task")


@pytest.mark.parametrize(
    "tool_calls, message",
    [
        ([{"name": "bash", "arguments": "{}"}], "missing a valid ID"),
        ([{"id": "x", "arguments": "{}"}], "missing a valid name"),
        (
            [
                {"id": "x", "name": "bash", "arguments": "{}"},
                {"id": "x", "name": "bash", "arguments": "{}"},
            ],
            "Duplicate",
        ),
    ],
)
def test_provider_protocol_errors_are_rejected(tool_calls, message):
    with pytest.raises(ToolCallProtocolError, match=message):
        normalize_tool_calls(tool_calls)


@pytest.mark.parametrize("arguments", ['{"x":', "[]", '"value"'])
def test_repairable_argument_errors_are_normalized(arguments):
    call = normalize_tool_calls([{"id": "x", "name": "bash", "arguments": arguments}])[0]
    assert call.arguments is None
    assert call.argument_error


def test_context_rejects_absolute_parent_and_symlink_escapes(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    context = ToolExecutionContext("session", workspace, "turn")

    with pytest.raises(WorkspaceBoundaryError):
        context.resolve_path("../outside/file.txt")
    with pytest.raises(WorkspaceBoundaryError):
        context.resolve_path(str(outside / "file.txt"))
    with pytest.raises(WorkspaceBoundaryError):
        context.resolve_path("link/file.txt")


@pytest.mark.asyncio
async def test_read_write_patch_and_bash_share_runtime_workspace(tmp_path):
    executor = _executor(tmp_path)
    write = await executor.execute("write_file", {"path": "file.txt", "content": "old"})
    assert write.success
    read = await executor.execute("read_file", {"path": "file.txt"})
    assert read.success and "old" in read.content

    marker = "***"
    patch_text = f"{marker} Begin Patch\n{marker} Update File: file.txt\n@@\n-old\n+new\n{marker} End Patch"
    patched = await executor.execute("apply_patch", {"patch": patch_text})
    assert patched.success
    bash = await executor.execute("bash", {"command": "pwd"})
    assert bash.success
    assert str(tmp_path.resolve()) in bash.content
    assert (tmp_path / "file.txt").read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_two_workspace_executors_are_isolated(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_executor = _executor(first)
    second_executor = _executor(second)
    await asyncio.gather(
        first_executor.execute("write_file", {"path": "same.txt", "content": "first"}),
        second_executor.execute("write_file", {"path": "same.txt", "content": "second"}),
    )
    assert (first / "same.txt").read_text() == "first"
    assert (second / "same.txt").read_text() == "second"


@pytest.mark.asyncio
async def test_bash_process_is_terminated_on_cancellation(tmp_path):
    executor = _executor(tmp_path)
    task = asyncio.create_task(executor.execute("bash", {"command": "sleep 2; printf escaped > should-not-exist"}))
    await asyncio.sleep(0.1)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.1)
    assert not (tmp_path / "should-not-exist").exists()


class _ToolCallingLLM:
    def __init__(self, call):
        self.call = call
        self.calls = 0
        self.tool_result = ""

    def chat(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(content="", tool_calls=[self.call], usage=None)
        self.tool_result = [message for message in messages if message.get("role") == "tool"][-1]["content"]
        return SimpleNamespace(content="done", tool_calls=None, usage=None)


@pytest.mark.asyncio
async def test_hidden_tool_call_is_denied_without_execution(tmp_path):
    with patch("amcp.agent.Path.home", return_value=tmp_path):
        agent = Agent(_spec(tools=None), session_id="hidden")
    llm = _ToolCallingLLM(
        {
            "id": "call-1",
            "name": "write_file",
            "arguments": json.dumps({"path": "forbidden.txt", "content": "no"}),
        }
    )
    think_spec = create_default_tool_registry(enable_task=False).get_tool("think").get_spec()
    result = await agent._enhanced_chat_with_tools(
        llm_client=llm,
        messages=[{"role": "user", "content": "test"}],
        tools=[think_spec],
        tool_registry={},
        stream=False,
        status=MagicMock(),
        work_dir=tmp_path,
    )
    assert result == "done"
    assert "permission denied" in llm.tool_result
    assert not (tmp_path / "forbidden.txt").exists()


@pytest.mark.asyncio
async def test_empty_allowlist_and_disabled_delegation_cannot_execute(tmp_path):
    registry = create_default_tool_registry(enable_task=True)
    cases = [
        (
            _spec(tools=[]),
            registry.get_tool("write_file").get_spec(),
            {
                "id": "write",
                "name": "write_file",
                "arguments": '{"path":"denied.txt","content":"no"}',
            },
        ),
        (
            _spec(tools=None, can_delegate=False),
            registry.get_tool("task").get_spec(),
            {
                "id": "task",
                "name": "task",
                "arguments": '{"action":"list"}',
            },
        ),
    ]
    for index, (spec, tool_spec, call) in enumerate(cases):
        with patch("amcp.agent.Path.home", return_value=tmp_path):
            agent = Agent(spec, session_id=f"denied-{index}")
        llm = _ToolCallingLLM(call)
        assert (
            await agent._enhanced_chat_with_tools(
                llm_client=llm,
                messages=[{"role": "user", "content": "test"}],
                tools=[tool_spec],
                tool_registry={},
                stream=False,
                status=MagicMock(),
                work_dir=tmp_path,
            )
            == "done"
        )
        assert "permission denied" in llm.tool_result
    assert not (tmp_path / "denied.txt").exists()


@pytest.mark.asyncio
async def test_invalid_arguments_are_repairable_but_missing_id_is_protocol_error(tmp_path):
    cfg = AMCPConfig(servers={}, chat=None, context=ContextConfig())
    with patch("amcp.agent.Path.home", return_value=tmp_path), patch("amcp.agent.load_config", return_value=cfg):
        agent = Agent(_spec(tools=None), session_id="malformed")
    bash_spec = create_default_tool_registry(enable_task=False).get_tool("bash").get_spec()
    llm = _ToolCallingLLM({"id": "call-1", "name": "bash", "arguments": "[]"})
    assert (
        await agent._enhanced_chat_with_tools(
            llm_client=llm,
            messages=[{"role": "user", "content": "test"}],
            tools=[bash_spec],
            tool_registry={},
            stream=False,
            status=MagicMock(),
            work_dir=tmp_path,
        )
        == "done"
    )
    assert "JSON object" in llm.tool_result

    bad_llm = _ToolCallingLLM({"name": "bash", "arguments": "{}"})
    with pytest.raises(ToolCallProtocolError):
        await agent._enhanced_chat_with_tools(
            llm_client=bad_llm,
            messages=[{"role": "user", "content": "test"}],
            tools=[bash_spec],
            tool_registry={},
            stream=False,
            status=MagicMock(),
            work_dir=tmp_path,
        )
