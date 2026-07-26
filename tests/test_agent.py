"""Tests for agent module."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amcp.agent import Agent, AgentExecutionError, BusyError, MaxStepsReached
from amcp.agent_spec import ResolvedAgentSpec
from amcp.config import AMCPConfig, ChatConfig, ContextConfig
from amcp.hooks import HookDecision, HookOutput
from amcp.llm import LLMResponse, TokenUsage
from amcp.memory import MemoryManager, MemoryStore
from amcp.multi_agent import AgentMode
from amcp.session_state import SessionState
from amcp.session_store import SessionLoadError
from amcp.tools import create_default_tool_registry


class TestAgentInit:
    def test_default_init(self):
        with patch("amcp.agent.load_config") as mock_load:
            mock_load.return_value = MagicMock()
            agent = Agent()
            assert agent.name == "default"
            assert agent.session_id is not None
            assert agent.conversation_history == []

    def test_custom_session_id(self):
        with patch("amcp.agent.load_config") as mock_load:
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")
            assert agent.session_id == "test-session"

    def test_custom_agent_spec(self):
        with patch("amcp.agent.load_config") as mock_load:
            mock_load.return_value = MagicMock()
            spec = ResolvedAgentSpec(
                name="custom",
                description="",
                mode=AgentMode.PRIMARY,
                system_prompt="",
                tools=[],
                exclude_tools=[],
                max_steps=10,
                model="",
                base_url="",
            )
            agent = Agent(agent_spec=spec)
            assert agent.name == "custom"
            assert agent.max_steps == 10

    def test_loads_existing_history(self, tmp_path):
        sessions_dir = tmp_path / ".config" / "amcp" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session_file = sessions_dir / "test-session.json"
        state = SessionState(session_id="test-session", agent_name="default")
        state.commit_turn(
            "turn-1",
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        )
        state.usage.total_llm_calls = 1
        data = {**state.to_snapshot(), "schema_version": 2}
        session_file.write_text(json.dumps(data))

        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent(session_id="test-session")
                assert len(agent.conversation_history) == 2
                assert agent.total_llm_calls == 1

    def test_load_history_handles_corrupted_file(self, tmp_path):
        session_file = tmp_path / ".config" / "amcp" / "sessions" / "test-session.json"
        session_file.parent.mkdir(parents=True)
        session_file.write_text("not json")

        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                with pytest.raises(SessionLoadError, match="Could not load session"):
                    Agent(session_id="test-session")


class TestAgentToolLimits:
    @pytest.mark.asyncio
    async def test_process_message_resets_per_request_tool_counts(self, tmp_path):
        """Per-request tool counts should not leak across Telegram messages."""

        async def deny_prompt(**_kwargs):
            return HookOutput(continue_execution=False, stop_reason="blocked")

        with (
            patch("amcp.agent.Path.home") as mock_home,
            patch("amcp.agent.load_config") as mock_load,
            patch("amcp.agent.run_user_prompt_hooks", side_effect=deny_prompt),
        ):
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")
            agent.current_conversation_tool_calls = [{"tool": "read_file"} for _ in range(100)]

            result = await agent._process_message("hello", tmp_path, stream=False, show_progress=False)

        assert result == "blocked"
        assert agent.current_conversation_tool_calls == []

    def test_read_file_session_limit_still_applies(self, tmp_path):
        """Resetting per-request counts must not remove the session-level cap."""
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")

        agent.tool_calls_history = [{"tool": "read_file"} for _ in range(600)]
        agent.current_conversation_tool_calls = []

        assert agent._should_limit_tool_calls("read_file") is True

    def test_bash_per_request_limit_applies(self, tmp_path):
        """Bash calls are capped per request to avoid oversized tool context."""
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")

            agent.current_conversation_tool_calls = [{"tool": "bash"} for _ in range(100)]

            assert agent._should_limit_tool_calls("bash") is True

    def test_bash_per_request_limit_is_configurable(self, tmp_path):
        """Config can tune the bash cap for long-running Telegram agents."""
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = AMCPConfig(servers={}, chat=ChatConfig(bash_tool_limit=20))
            agent = Agent(session_id="test-session")

            agent.current_conversation_tool_calls = [{"tool": "bash"} for _ in range(19)]
            assert agent._should_limit_tool_calls("bash") is False

            agent.current_conversation_tool_calls = [{"tool": "bash"} for _ in range(20)]
            assert agent._should_limit_tool_calls("bash") is True

    def test_bash_per_request_limit_can_be_disabled(self, tmp_path):
        """Non-positive bash_tool_limit disables only the bash-specific cap."""
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = AMCPConfig(servers={}, chat=ChatConfig(bash_tool_limit=0))
            agent = Agent(session_id="test-session")

            agent.current_conversation_tool_calls = [{"tool": "bash"} for _ in range(500)]

            assert agent._should_limit_tool_calls("bash") is False

    def test_bash_limit_resets_for_new_request(self, tmp_path):
        """A new user request can use bash again after per-request reset."""
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")

        agent.current_conversation_tool_calls = []

        assert agent._should_limit_tool_calls("bash") is False

    @pytest.mark.asyncio
    async def test_bash_tool_receives_work_dir(self, tmp_path):
        """Agent should run bash tool calls from the request work_dir."""

        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return SimpleNamespace(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "name": "bash",
                                "arguments": json.dumps({"command": "pwd"}),
                            }
                        ],
                    )

                tool_messages = [m for m in messages if m.get("role") == "tool"]
                assert tool_messages
                assert str(tmp_path.resolve()) in tool_messages[-1]["content"]
                return SimpleNamespace(content="done", tool_calls=None)

        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = AMCPConfig(servers={}, chat=None, context=ContextConfig())
            agent = Agent(session_id="test-session")

        result = await agent._enhanced_chat_with_tools(
            llm_client=FakeLLM(),
            messages=[{"role": "user", "content": "pwd"}],
            tools=[create_default_tool_registry(enable_task=False).get_tool("bash").get_spec()],
            tool_registry={},
            stream=False,
            status=MagicMock(),
            work_dir=tmp_path,
        )

        assert result == "done"

    @pytest.mark.asyncio
    async def test_retries_with_repaired_pairing_after_provider_pairing_error(self, tmp_path):
        """A Gemini-style pairing 400 triggers one retry with synthesized tool results."""

        pairing_error = RuntimeError(
            "Error code: 400 - {'error': {'message': 'Please ensure that the number of "
            "function response parts is equal to the number of function call parts of the "
            "function call turn.', 'status': 'INVALID_ARGUMENT'}}"
        )

        class FakeLLM:
            def __init__(self):
                self.calls = 0
                self.seen_messages = None

            def chat(self, messages, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise pairing_error
                self.seen_messages = messages
                return SimpleNamespace(content="recovered", tool_calls=None)

        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = AMCPConfig(servers={}, chat=None, context=ContextConfig())
            agent = Agent(session_id="test-session")

        llm = FakeLLM()
        result = await agent._enhanced_chat_with_tools(
            llm_client=llm,
            messages=[
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "missing",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "user", "content": "continue"},
            ],
            tools=[],
            tool_registry={},
            stream=False,
            status=MagicMock(),
            work_dir=tmp_path,
        )

        assert result == "recovered"
        assert llm.calls == 2
        retried_roles = [message["role"] for message in llm.seen_messages]
        assert retried_roles == ["assistant", "tool", "user"]
        synthesized = llm.seen_messages[1]
        assert synthesized["tool_call_id"] == "missing"
        assert synthesized["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_grep_path_is_canonicalized_before_pre_tool_hooks(self, tmp_path):
        """Hooks inspect grep's canonical paths argument rather than its alias."""

        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return SimpleNamespace(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "name": "grep",
                                "arguments": json.dumps({"pattern": "needle", "path": "src"}),
                            }
                        ],
                    )
                assert any(message.get("role") == "tool" for message in messages)
                return SimpleNamespace(content="done", tool_calls=None)

        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = AMCPConfig(servers={}, chat=None, context=ContextConfig())
            agent = Agent(session_id="test-session")

        denied = HookOutput(decision=HookDecision.DENY, decision_reason="test")
        with patch(
            "amcp.agent.run_pre_tool_use_hooks",
            new_callable=AsyncMock,
            return_value=denied,
        ) as pre_hook:
            result = await agent._enhanced_chat_with_tools(
                llm_client=FakeLLM(),
                messages=[{"role": "user", "content": "search"}],
                tools=[create_default_tool_registry(enable_task=False).get_tool("grep").get_spec()],
                tool_registry={},
                stream=False,
                status=MagicMock(),
                work_dir=tmp_path,
            )

        assert result == "done"
        assert pre_hook.await_args.kwargs["tool_input"] == {
            "pattern": "needle",
            "paths": ["src"],
        }


class TestAgentHistoryManagement:
    def test_clear_conversation_history(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent(session_id="test-session")
                agent.conversation_history = [{"role": "user", "content": "hi"}]
                agent.tool_calls_history = [{"tool": "test"}]
                agent.total_llm_calls = 5
                agent.clear_conversation_history()
                assert agent.conversation_history == []
                assert agent.tool_calls_history == []
                assert agent.total_llm_calls == 0

    def test_get_conversation_summary(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent(session_id="test-session")
                agent.conversation_history = [{"role": "user", "content": "hi"}]
                agent.tool_calls_history = [{"tool": "test"}]
                agent.total_llm_calls = 3
                summary = agent.get_conversation_summary()
                assert summary["session_id"] == "test-session"
                assert summary["message_count"] == 1
                assert summary["total_tool_calls"] == 1
                assert summary["total_llm_calls"] == 3

    def test_memory_prompt_context_is_frozen_per_root(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")

        manager = MagicMock()
        manager.get_persona_context.return_value = "persona"
        manager.get_memory_context.return_value = "memory"

        with patch("amcp.agent.get_memory_manager", return_value=manager) as get_manager:
            assert agent._get_memory_prompt_context(tmp_path) == ("persona", "memory")
            manager.get_persona_context.return_value = "changed-persona"
            manager.get_memory_context.return_value = "changed-memory"
            assert agent._get_memory_prompt_context(tmp_path) == ("persona", "memory")

        get_manager.assert_called_once_with(tmp_path.resolve())

    def test_reset_memory_context_snapshot_refreshes_memory(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")

        first = MagicMock()
        first.get_persona_context.return_value = "first-persona"
        first.get_memory_context.return_value = "first-memory"
        second = MagicMock()
        second.get_persona_context.return_value = "second-persona"
        second.get_memory_context.return_value = "second-memory"

        with patch("amcp.agent.get_memory_manager", side_effect=[first, second]):
            assert agent._get_memory_prompt_context(tmp_path) == ("first-persona", "first-memory")
            agent.reset_memory_context_snapshot()
            assert agent._get_memory_prompt_context(tmp_path) == ("second-persona", "second-memory")

    @pytest.mark.asyncio
    async def test_periodic_memory_review_runs_every_ten_user_turns(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")

        conversation = []
        for idx in range(10):
            conversation.extend(
                [
                    {"role": "user", "content": f"u{idx}"},
                    {"role": "assistant", "content": f"a{idx}"},
                ]
            )

        with patch.object(agent, "_run_isolated_memory_review", new_callable=AsyncMock) as review:
            await agent._maybe_run_periodic_memory_review(
                conversation_snapshot=conversation,
                system_prompt="system",
                work_dir=tmp_path,
                status=MagicMock(),
            )

        tasks = list(agent._pending_memory_review_tasks)
        assert len(tasks) == 1
        await tasks[0]
        review.assert_awaited_once()
        assert agent._last_memory_review_turn_count == 10

    @pytest.mark.asyncio
    async def test_flush_memory_marks_reviewed_turn_count(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")
        agent.conversation_history = [
            {"role": "user", "content": "remember I prefer concise replies"},
            {"role": "assistant", "content": "ok"},
        ]

        with (
            patch.object(agent, "_get_system_prompt", return_value="system"),
            patch.object(agent, "_run_memory_review", new_callable=AsyncMock, return_value=True) as review,
        ):
            saved = await agent.flush_memory(work_dir=tmp_path)

        assert saved is True
        review.assert_awaited_once()
        assert agent._last_memory_review_turn_count == 1

    def test_save_conversation_history(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent(session_id="test-session")
                agent._session_state.commit_turn(
                    "turn-1",
                    [
                        {"role": "user", "content": "hi"},
                        {"role": "assistant", "content": "hello"},
                    ],
                )
                agent._apply_session_state(agent._session_state)
                agent._save_conversation_history()
                assert agent.session_file.exists()
                data = json.loads(agent.session_file.read_text())
                assert data["schema_version"] == 2
                assert data["conversation"]["messages"] == [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ]


class TestAgentContextBudget:
    def test_fit_tool_context_synthesizes_missing_tool_results(self):
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "kept",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    },
                    {
                        "id": "lost",
                        "type": "function",
                        "function": {"name": "grep", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "kept", "content": "file contents"},
            {"role": "user", "content": "go on"},
        ]

        fitted = Agent._fit_tool_context(messages, [], 10**9)

        roles = [message["role"] for message in fitted]
        assert roles == ["system", "assistant", "tool", "tool", "user"]
        synthesized = fitted[3]
        assert synthesized["tool_call_id"] == "lost"
        assert synthesized["name"] == "grep"
        assert "synthesized" in synthesized["content"]
        assert messages[2]["role"] == "tool" and len(messages) == 4

    def test_fit_tool_context_drops_orphaned_tool_results(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "tool", "tool_call_id": "orphan", "content": "stale"},
            {"role": "user", "content": "hello"},
        ]

        fitted = Agent._fit_tool_context(messages, [], 10**9)

        assert [message["role"] for message in fitted] == ["system", "user"]

    def test_fit_tool_context_trims_old_result_without_mutating_input(self):
        old_content = "old result " * 3000
        latest_content = "latest result " * 1000
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "old",
                        "type": "function",
                        "function": {"name": "web_fetch", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "old", "content": old_content},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "latest",
                        "type": "function",
                        "function": {"name": "web_fetch", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "latest", "content": latest_content},
        ]
        budget = 5000

        fitted = Agent._fit_tool_context(messages, [], budget)

        assert "trimmed for context budget" in fitted[2]["content"]
        assert fitted[4]["content"] == latest_content
        assert messages[2]["content"] == old_content

    def test_records_provider_usage_for_status(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")

        response = LLMResponse(
            content="done",
            usage=TokenUsage(
                input_tokens=10_000,
                output_tokens=500,
                total_tokens=12_500,
                cached_input_tokens=2_000,
            ),
        )
        agent.total_llm_calls = 1

        agent._record_llm_usage(response, estimated_input_tokens=10_000, context_window=64_000)

        usage = agent.get_token_usage_summary()
        assert usage["context_tokens"] == 12_000
        assert usage["context_usage_ratio"] == 0.1875
        assert usage["total_tokens"] == 12_500
        assert usage["total_cached_input_tokens"] == 2_000
        assert usage["total_cache_write_input_tokens"] == 0
        assert usage["last_usage_from_api"] is True

    def test_estimates_input_when_provider_omits_usage(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent(session_id="test-session")

        agent.total_llm_calls = 1
        agent._record_llm_usage(
            LLMResponse(content="done"),
            estimated_input_tokens=8_000,
            context_window=64_000,
        )

        usage = agent.get_token_usage_summary()
        assert usage["context_tokens"] == 8_000
        assert usage["total_input_tokens"] == 8_000
        assert usage["last_output_tokens"] is None
        assert usage["estimated_input_llm_calls"] == 1
        assert usage["last_usage_from_api"] is False


class TestAgentEventCallbacks:
    def test_add_and_emit_event(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent()
                events = []

                def callback(event_type, data):
                    events.append((event_type, data))

                agent.add_event_callback(callback)
                agent._emit_event("test.event", {"key": "value"})
                assert len(events) == 1
                assert events[0][0] == "test.event"
                assert events[0][1]["key"] == "value"

    def test_remove_event_callback(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent()
                events = []

                def callback(event_type, data):
                    events.append((event_type, data))

                agent.add_event_callback(callback)
                agent.remove_event_callback(callback)
                agent._emit_event("test.event", {})
                assert len(events) == 0

    def test_emit_event_suppresses_callback_errors(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent()

                def bad_callback(event_type, data):
                    raise RuntimeError("boom")

                agent.add_event_callback(bad_callback)
                # Should not raise
                agent._emit_event("test.event", {})


class TestAgentContextBudget:
    def test_resolve_model_name_from_spec(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                spec = ResolvedAgentSpec(
                    name="test",
                    description="",
                    mode=AgentMode.PRIMARY,
                    system_prompt="",
                    tools=[],
                    exclude_tools=[],
                    max_steps=20,
                    model="gpt-5.5",
                    base_url="",
                )
                agent = Agent(agent_spec=spec)
                assert agent._resolve_model_name() == "gpt-5.5"

    def test_resolve_model_name_fallback(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_cfg = MagicMock()
                mock_cfg.chat = None
                mock_load.return_value = mock_cfg
                agent = Agent()
                assert agent._resolve_model_name() == "DeepSeek-V3.1-Terminus"

    def test_trim_to_token_budget_empty(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent()
                assert agent._trim_to_token_budget("", 100) == ""

    def test_trim_to_token_budget_within_budget(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent()
                text = "short text"
                assert agent._trim_to_token_budget(text, 1000) == text

    def test_system_prompt_includes_persona_and_memory(self, tmp_path):
        """System prompt includes durable soul, identity, and memory."""
        manager = MemoryManager(project_root=tmp_path / "project")
        manager.user_store = MemoryStore(tmp_path / "user-memory")
        manager.write_soul("Soul marker: careful continuity", scope="user")
        manager.write_identity("Identity marker: AMCP Atlas", scope="user")
        manager.write_long_term("Memory marker: user prefers concise replies", scope="user")

        cfg = AMCPConfig(servers={}, chat=None, context=ContextConfig())
        with (
            patch("amcp.agent.Path.home") as mock_home,
            patch("amcp.agent.load_config", return_value=cfg),
            patch("amcp.agent.get_memory_manager", return_value=manager),
        ):
            mock_home.return_value = tmp_path
            agent = Agent()
            prompt = agent._get_system_prompt(tmp_path / "project")

        assert "Soul marker: careful continuity" in prompt
        assert "Identity marker: AMCP Atlas" in prompt
        assert "Memory marker: user prefers concise replies" in prompt


class TestAgentToolRegistry:
    def test_tool_registry_initialized(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent()
                assert agent.tool_registry is not None


class TestAgentStepTracking:
    def test_step_count_starts_at_zero(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent()
                assert agent.step_count == 0

    def test_request_counters_reset(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent()
                agent.current_request_tool_calls = 5
                agent.current_request_llm_calls = 3
                agent.current_request_start_time = 12345.0
                agent.current_request_tool_calls = 0
                agent.current_request_llm_calls = 0
                agent.current_request_start_time = None
                assert agent.current_request_tool_calls == 0
                assert agent.current_request_llm_calls == 0


class TestAgentMemoryReview:
    """Tests for pre-compaction memory flush."""

    def test_run_memory_review_exists(self, tmp_path):
        """Agent has _run_memory_review method."""
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock()
            agent = Agent()
            assert hasattr(agent, "_run_memory_review")

    def test_system_prompt_includes_memory_guidance(self, tmp_path):
        """System prompt includes MEMORY_GUIDANCE text."""
        manager = MemoryManager(project_root=tmp_path / "project")
        manager.user_store = MemoryStore(tmp_path / "user-memory")

        cfg = AMCPConfig(servers={}, chat=None, context=ContextConfig())
        with (
            patch("amcp.agent.Path.home") as mock_home,
            patch("amcp.agent.load_config", return_value=cfg),
            patch("amcp.agent.get_memory_manager", return_value=manager),
        ):
            mock_home.return_value = tmp_path
            agent = Agent()
            prompt = agent._get_system_prompt(tmp_path / "project")

        assert "memory_guidance" in prompt
        assert "write_soul" in prompt
        assert "upsert_fact" in prompt
        assert "declarative facts" in prompt


def test_process_message_wraps_markup_like_exceptions(tmp_path):
    async def _run():
        with patch("amcp.agent.Path.home") as mock_home, patch("amcp.agent.load_config") as mock_load:
            mock_home.return_value = tmp_path
            mock_load.return_value = MagicMock(chat=None)
            agent = Agent(session_id="test-session")

        prompt_hook_output = SimpleNamespace(
            continue_execution=True,
            feedback=None,
            stop_reason=None,
        )
        status = SimpleNamespace(update=lambda *args, **kwargs: None)
        markup_error = "closing tag '[/llms.txt]' at position 48 doesn't match any open tag"

        with (
            patch("amcp.agent.run_user_prompt_hooks", return_value=prompt_hook_output),
            patch.object(agent, "_create_progress_context") as mock_progress,
            patch.object(agent, "_get_system_prompt", return_value="system"),
            patch.object(agent, "_build_tools_and_registry") as mock_build_tools,
            patch.object(agent, "_run_with_tools", side_effect=ValueError(markup_error)),
        ):
            mock_progress.return_value.__enter__.return_value = status
            mock_progress.return_value.__exit__.return_value = False
            mock_build_tools.return_value = ([], {})

            with pytest.raises(AgentExecutionError, match="Agent execution failed"):
                await agent._process_message("search e2b persistence", tmp_path, stream=False, show_progress=False)

    asyncio.run(_run())


@pytest.mark.asyncio
async def test_process_message_preserves_max_steps_exception(tmp_path):
    cfg = AMCPConfig(servers={}, chat=None, context=ContextConfig())
    with patch("amcp.agent.Path.home", return_value=tmp_path), patch("amcp.agent.load_config", return_value=cfg):
        agent = Agent(session_id="max-steps")
    prompt_hook_output = SimpleNamespace(
        continue_execution=True,
        feedback=None,
        stop_reason=None,
    )
    status = SimpleNamespace(update=lambda *args, **kwargs: None)
    with (
        patch("amcp.agent.run_user_prompt_hooks", return_value=prompt_hook_output),
        patch("amcp.llm.create_llm_client", return_value=MagicMock()),
        patch.object(agent, "_create_progress_context") as progress,
        patch.object(agent, "_get_system_prompt", return_value="system"),
        patch.object(agent, "_build_tools_and_registry", return_value=([], {})),
        patch.object(agent, "_run_with_tools", side_effect=MaxStepsReached(1)),
    ):
        progress.return_value.__enter__.return_value = status
        progress.return_value.__exit__.return_value = False
        with pytest.raises(MaxStepsReached):
            await agent._process_message("test", tmp_path, stream=False, show_progress=False)
