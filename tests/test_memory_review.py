"""Tests for the memory review module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from amcp.config import AMCPConfig
from amcp.memory_review import MEMORY_GUIDANCE, MEMORY_REVIEW_PROMPT, run_memory_review
from amcp.tool_execution import ToolCapability, ToolExecutionContext, ToolExecutor


class TestMemoryGuidance:
    """Tests for MEMORY_GUIDANCE constant."""

    def test_guidance_contains_key_instructions(self):
        """Guidance text includes all key memory actions."""
        assert "write_soul" in MEMORY_GUIDANCE
        assert "write_identity" in MEMORY_GUIDANCE
        assert "upsert_fact" in MEMORY_GUIDANCE
        assert "write" in MEMORY_GUIDANCE
        assert "append" in MEMORY_GUIDANCE
        assert "search" in MEMORY_GUIDANCE

    def test_guidance_contains_when_to_save(self):
        """Guidance explains when to save memories."""
        assert "durable preference" in MEMORY_GUIDANCE.lower()
        assert "personality" in MEMORY_GUIDANCE.lower()
        assert "identity" in MEMORY_GUIDANCE.lower()

    def test_guidance_contains_when_not_to_save(self):
        """Guidance explains what NOT to save."""
        assert "NOT to save" in MEMORY_GUIDANCE
        assert "stale" in MEMORY_GUIDANCE.lower()

    def test_guidance_contains_format_rules(self):
        """Guidance explains declarative fact format."""
        assert "declarative facts" in MEMORY_GUIDANCE
        assert "User prefers concise replies" in MEMORY_GUIDANCE


class TestMemoryReviewPrompt:
    """Tests for MEMORY_REVIEW_PROMPT constant."""

    def test_prompt_asks_about_user_preferences(self):
        """Review prompt asks about user preferences."""
        assert "preferences" in MEMORY_REVIEW_PROMPT.lower()
        assert "persona" in MEMORY_REVIEW_PROMPT.lower()

    def test_prompt_asks_about_identity(self):
        """Review prompt asks about identity/soul."""
        assert "identity" in MEMORY_REVIEW_PROMPT.lower()
        assert "soul" in MEMORY_REVIEW_PROMPT.lower()

    def test_prompt_handles_nothing_to_save(self):
        """Review prompt allows 'Nothing to save.' response."""
        assert "Nothing to save." in MEMORY_REVIEW_PROMPT


class TestRunMemoryReview:
    """Tests for run_memory_review function."""

    def test_review_with_no_tool_calls(self):
        """Review returns content when LLM doesn't call tools."""
        mock_client = MagicMock()
        mock_client.achat = AsyncMock(return_value=MagicMock(content="Nothing to save.", tool_calls=None))

        result = asyncio.run(
            run_memory_review(
                client=mock_client,
                model="test-model",
                system_prompt="You are a test agent.",
                conversation_snapshot=[{"role": "user", "content": "Hello"}],
                tools=[{"type": "function", "function": {"name": "memory"}}],
                tool_executor=MagicMock(),
            )
        )

        assert result == "Nothing to save."
        mock_client.achat.assert_called_once()

    def test_review_with_tool_call(self):
        """Review executes memory tool calls and loops."""
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=MagicMock(success=True, content="Fact saved.", error=None))

        # First call returns tool_call, second returns final text
        mock_client = MagicMock()
        mock_client.achat = AsyncMock(
            side_effect=[
                MagicMock(
                    content=None,
                    tool_calls=[
                        {
                            "name": "memory",
                            "id": "tc1",
                            "arguments": '{"action": "upsert_fact", "key": "test", "content": "value"}',
                        }
                    ],
                ),
                MagicMock(content="Saved user preference.", tool_calls=None),
            ]
        )

        result = asyncio.run(
            run_memory_review(
                client=mock_client,
                model="test-model",
                system_prompt="You are a test agent.",
                conversation_snapshot=[{"role": "user", "content": "I prefer TypeScript"}],
                tools=[{"type": "function", "function": {"name": "memory"}}],
                tool_executor=mock_executor,
            )
        )

        assert result == "Saved user preference."
        assert mock_client.achat.call_count == 2
        mock_executor.execute.assert_awaited_once_with(
            "memory",
            {"action": "upsert_fact", "key": "test", "content": "value"},
        )

    @pytest.mark.parametrize("tool_name", ["bash", "../memory"])
    def test_review_denies_unexposed_tool_names(self, tmp_path, tool_name):
        """A review cannot execute malicious names through the global registry."""
        registry = MagicMock()
        executor = ToolExecutor(
            context=ToolExecutionContext("session", tmp_path, "review"),
            capability=ToolCapability.from_spec(["memory"], [], False),
            exposed_tools={"memory"},
            registry=registry,
            mcp_registry={},
            config=AMCPConfig(servers={}, chat=None),
        )
        mock_client = MagicMock()
        mock_client.achat = AsyncMock(
            side_effect=[
                MagicMock(
                    content=None,
                    tool_calls=[{"name": tool_name, "id": "tc1", "arguments": "{}"}],
                ),
                MagicMock(content="Nothing to save.", tool_calls=None),
            ]
        )

        result = asyncio.run(
            run_memory_review(
                client=mock_client,
                model="test-model",
                system_prompt="test",
                conversation_snapshot=[],
                tools=[{"type": "function", "function": {"name": "memory"}}],
                tool_executor=executor,
            )
        )

        assert result == "Nothing to save."
        registry.execute_tool.assert_not_called()
        tool_message = mock_client.achat.await_args_list[1].kwargs["messages"][-1]
        assert "not authorized" in tool_message["content"]

    def test_review_rejects_invalid_tool_name(self):
        """A structurally invalid tool name aborts without execution."""
        executor = MagicMock()
        executor.execute = AsyncMock()
        mock_client = MagicMock()
        mock_client.achat = AsyncMock(
            return_value=MagicMock(
                content=None,
                tool_calls=[{"name": "", "id": "tc1", "arguments": "{}"}],
            )
        )

        result = asyncio.run(
            run_memory_review(
                client=mock_client,
                model="test-model",
                system_prompt="test",
                conversation_snapshot=[],
                tools=[{"type": "function", "function": {"name": "memory"}}],
                tool_executor=executor,
            )
        )

        assert result == ""
        executor.execute.assert_not_awaited()

    def test_review_handles_errors_gracefully(self):
        """Review returns empty string on failure."""
        mock_client = MagicMock()
        mock_client.achat = AsyncMock(side_effect=RuntimeError("API error"))

        result = asyncio.run(
            run_memory_review(
                client=mock_client,
                model="test-model",
                system_prompt="test",
                conversation_snapshot=[],
                tools=[],
                tool_executor=MagicMock(),
            )
        )

        assert result == ""
