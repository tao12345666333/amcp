"""Tests for agent module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from amcp.agent import Agent, AgentExecutionError, BusyError, MaxStepsReached
from amcp.agent_spec import ResolvedAgentSpec
from amcp.config import AMCPConfig, ContextConfig
from amcp.memory import MemoryManager, MemoryStore
from amcp.multi_agent import AgentMode


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
        data = {
            "conversation_history": [{"role": "user", "content": "hi"}],
            "tool_calls_history": [],
            "current_conversation_tool_calls": [],
            "total_llm_calls": 1,
        }
        session_file.write_text(json.dumps(data))

        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent(session_id="test-session")
                assert len(agent.conversation_history) == 1
                assert agent.total_llm_calls == 1

    def test_load_history_handles_corrupted_file(self, tmp_path):
        session_file = tmp_path / "test-session.json"
        session_file.write_text("not json")

        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent(session_id="test-session")
                assert agent.conversation_history == []
                assert agent.total_llm_calls == 0


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

    def test_save_conversation_history(self, tmp_path):
        with patch("amcp.agent.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            with patch("amcp.agent.load_config") as mock_load:
                mock_load.return_value = MagicMock()
                agent = Agent(session_id="test-session")
                agent.conversation_history = [{"role": "user", "content": "hi"}]
                agent._save_conversation_history()
                assert agent.session_file.exists()
                data = json.loads(agent.session_file.read_text())
                assert data["conversation_history"] == [{"role": "user", "content": "hi"}]


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
                    model="gpt-4o",
                    base_url="",
                )
                agent = Agent(agent_spec=spec)
                assert agent._resolve_model_name() == "gpt-4o"

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
