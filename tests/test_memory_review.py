"""Tests for the memory review module."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from amcp.memory_review import MEMORY_GUIDANCE, MEMORY_REVIEW_PROMPT, run_memory_review


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
        mock_client.chat.return_value = MagicMock(content="Nothing to save.", tool_calls=None)

        result = asyncio.run(
            run_memory_review(
                client=mock_client,
                model="test-model",
                system_prompt="You are a test agent.",
                conversation_snapshot=[{"role": "user", "content": "Hello"}],
                tools=[{"type": "function", "function": {"name": "memory"}}],
                tool_registry=MagicMock(),
            )
        )

        assert result == "Nothing to save."
        mock_client.chat.assert_called_once()

    def test_review_with_tool_call(self):
        """Review executes memory tool calls and loops."""
        mock_registry = MagicMock()
        mock_registry.execute_tool.return_value = MagicMock(success=True, content="Fact saved.", error=None)

        # First call returns tool_call, second returns final text
        mock_client = MagicMock()
        mock_client.chat.side_effect = [
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

        result = asyncio.run(
            run_memory_review(
                client=mock_client,
                model="test-model",
                system_prompt="You are a test agent.",
                conversation_snapshot=[{"role": "user", "content": "I prefer TypeScript"}],
                tools=[{"type": "function", "function": {"name": "memory"}}],
                tool_registry=mock_registry,
            )
        )

        assert result == "Saved user preference."
        assert mock_client.chat.call_count == 2
        mock_registry.execute_tool.assert_called_once_with("memory", action="upsert_fact", key="test", content="value")

    def test_review_handles_errors_gracefully(self):
        """Review returns empty string on failure."""
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("API error")

        result = asyncio.run(
            run_memory_review(
                client=mock_client,
                model="test-model",
                system_prompt="test",
                conversation_snapshot=[],
                tools=[],
                tool_registry=MagicMock(),
            )
        )

        assert result == ""
