"""Tests for the smart compaction module."""

from unittest.mock import MagicMock

import pytest

from amcp.compaction import (
    CompactionConfig,
    CompactionResult,
    CompactionStrategy,
    SmartCompactor,
    estimate_tokens,
    get_model_context_window,
)


class TestGetModelContextWindow:
    """Tests for get_model_context_window function."""

    def test_exact_match_gpt4(self):
        """Test exact match for GPT-4."""
        assert get_model_context_window("gpt-4") == 8_192

    def test_exact_match_gpt4_turbo(self):
        """Test exact match for GPT-4 Turbo."""
        assert get_model_context_window("gpt-4-turbo") == 128_000

    def test_exact_match_claude(self):
        """Test exact match for Claude."""
        assert get_model_context_window("claude-3.5-sonnet") == 200_000

    def test_exact_match_gemini(self):
        """Test exact match for Gemini."""
        assert get_model_context_window("gemini-1.5-pro") == 2_000_000

    def test_partial_match_gpt4o(self):
        """Test partial matching for GPT-4o models."""
        # gpt-4o should match
        result = get_model_context_window("gpt-4o-2024-05-13")
        assert result == 128_000

    def test_partial_match_claude(self):
        """Test partial matching for Claude."""
        result = get_model_context_window("claude-3-opus-20240229")
        assert result == 200_000

    def test_deepseek_model(self):
        """Test DeepSeek model detection.

        Note: values come from models_db BUILTIN_MODELS which may differ
        from older hardcoded values.
        """
        # models_db has deepseek-chat as 128K (from models.dev data)
        assert get_model_context_window("deepseek-chat") == 128_000
        # For models not in BUILTIN_MODELS, falls back to pattern matching
        # which may give different results
        deepseek_v3 = get_model_context_window("deepseek-v3")
        assert deepseek_v3 >= 64_000  # At least 64K

    def test_qwen_model(self):
        """Test Qwen model detection."""
        assert get_model_context_window("qwen-2.5") == 128_000

    def test_glm_model(self):
        """Test GLM model detection.

        Note: models_db has updated values for GLM models.
        """
        glm4 = get_model_context_window("glm-4")
        assert glm4 >= 128_000
        # glm-4.6 is in BUILTIN_MODELS as 200K
        assert get_model_context_window("glm-4.6") == 200_000

    def test_unknown_model_returns_default(self):
        """Test unknown model returns default window."""
        result = get_model_context_window("some-unknown-model-xyz")
        assert result == 32_000  # DEFAULT_CONTEXT_WINDOW


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_messages(self):
        """Test with empty message list."""
        assert estimate_tokens([]) == 0

    def test_simple_message(self):
        """Test with a simple text message."""
        messages = [{"role": "user", "content": "Hello, world!"}]
        tokens = estimate_tokens(messages)
        assert tokens > 0
        assert tokens < 100  # Should be small

    def test_multiple_messages(self):
        """Test with multiple messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there! How can I help you?"},
            {"role": "user", "content": "Tell me about Python"},
        ]
        tokens = estimate_tokens(messages)
        assert tokens > 0

    def test_long_content(self):
        """Test with long content."""
        long_text = "word " * 1000  # ~5000 characters
        messages = [{"role": "user", "content": long_text}]
        tokens = estimate_tokens(messages)
        # Should estimate roughly 1000+ tokens (4 chars per token)
        assert tokens > 500

    def test_message_with_tool_calls(self):
        """Test message with tool calls."""
        messages = [
            {
                "role": "assistant",
                "content": "Let me read that file.",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "name": "read_file",
                        "arguments": '{"path": "/test.py"}',
                    }
                ],
            }
        ]
        tokens = estimate_tokens(messages)
        assert tokens > 0


class TestCompactionConfig:
    """Tests for CompactionConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = CompactionConfig()
        assert config.strategy == CompactionStrategy.SUMMARY
        assert config.threshold_ratio == 0.7
        assert config.target_ratio == 0.3
        assert config.preserve_last == 6
        assert config.preserve_tool_results is True
        assert config.safety_margin == 0.1

    def test_custom_values(self):
        """Test custom configuration values."""
        config = CompactionConfig(
            strategy=CompactionStrategy.HYBRID,
            threshold_ratio=0.8,
            target_ratio=0.4,
            preserve_last=10,
        )
        assert config.strategy == CompactionStrategy.HYBRID
        assert config.threshold_ratio == 0.8
        assert config.target_ratio == 0.4
        assert config.preserve_last == 10


class TestCompactionStrategy:
    """Tests for CompactionStrategy enum."""

    def test_strategies_exist(self):
        """Test all strategies are defined."""
        assert CompactionStrategy.SUMMARY.value == "summary"
        assert CompactionStrategy.TRUNCATE.value == "truncate"
        assert CompactionStrategy.SLIDING_WINDOW.value == "sliding_window"
        assert CompactionStrategy.HYBRID.value == "hybrid"


class TestSmartCompactor:
    """Tests for SmartCompactor class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock OpenAI client."""
        client = MagicMock()
        # Mock successful completion response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Compacted summary of the conversation."
        client.chat.completions.create.return_value = mock_response
        return client

    def test_init_calculates_thresholds(self, mock_client):
        """Test that init calculates thresholds based on model."""
        compactor = SmartCompactor(mock_client, model="gpt-4-turbo")

        assert compactor.context_window == 128_000
        # threshold = 128000 * 0.9 * 0.7 ≈ 80640
        assert compactor.threshold_tokens > 70000
        assert compactor.threshold_tokens < 90000
        # target = 128000 * 0.9 * 0.3 ≈ 34560
        assert compactor.target_tokens > 30000
        assert compactor.target_tokens < 40000

    def test_init_with_small_model(self, mock_client):
        """Test thresholds for smaller context window."""
        compactor = SmartCompactor(mock_client, model="gpt-4")

        assert compactor.context_window == 8_192
        assert compactor.threshold_tokens < 8_192
        assert compactor.target_tokens < compactor.threshold_tokens

    def test_should_compact_false_for_small_context(self, mock_client):
        """Test should_compact returns False for small contexts."""
        compactor = SmartCompactor(mock_client, model="gpt-4-turbo")

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        assert compactor.should_compact(messages) is False

    def test_should_compact_false_below_minimum(self, mock_client):
        """Test should_compact returns False below minimum threshold."""
        config = CompactionConfig(min_tokens_to_compact=10000)
        compactor = SmartCompactor(mock_client, model="gpt-4-turbo", config=config)

        # Create content that's ~500 tokens
        messages = [{"role": "user", "content": "x" * 2000}]
        assert compactor.should_compact(messages) is False

    def test_get_token_usage(self, mock_client):
        """Test get_token_usage returns correct structure."""
        compactor = SmartCompactor(mock_client, model="gpt-4-turbo")

        messages = [{"role": "user", "content": "Hello world"}]
        usage = compactor.get_token_usage(messages)

        assert "current_tokens" in usage
        assert "context_window" in usage
        assert "threshold_tokens" in usage
        assert "target_tokens" in usage
        assert "usage_ratio" in usage
        assert "should_compact" in usage
        assert "headroom_tokens" in usage

        assert usage["context_window"] == 128_000
        assert isinstance(usage["usage_ratio"], float)

    def test_compact_empty_messages(self, mock_client):
        """Test compact with empty messages."""
        compactor = SmartCompactor(mock_client, model="gpt-4-turbo")

        result_msgs, result = compactor.compact([])

        assert result_msgs == []
        assert result.original_tokens == 0
        assert result.compacted_tokens == 0
        assert result.messages_removed == 0

    def test_compact_preserves_recent(self, mock_client):
        """Test compact preserves recent messages."""
        config = CompactionConfig(preserve_last=2)
        compactor = SmartCompactor(mock_client, model="gpt-4-turbo", config=config)

        messages = [
            {"role": "user", "content": "Old message 1"},
            {"role": "assistant", "content": "Old response 1"},
            {"role": "user", "content": "Old message 2"},
            {"role": "assistant", "content": "Old response 2"},
            {"role": "user", "content": "Recent message"},
            {"role": "assistant", "content": "Recent response"},
        ]

        result_msgs, result = compactor.compact(messages)

        # Should have summary + preserved messages
        assert len(result_msgs) >= 2
        assert result.messages_preserved >= 2

    def test_compact_with_truncate_strategy(self, mock_client):
        """Test compact with truncate strategy."""
        config = CompactionConfig(strategy=CompactionStrategy.TRUNCATE, preserve_last=2)
        compactor = SmartCompactor(mock_client, model="gpt-4-turbo", config=config)

        messages = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
            {"role": "assistant", "content": "Response 3"},
        ]

        result_msgs, result = compactor.compact(messages)

        assert result.strategy_used == CompactionStrategy.TRUNCATE
        assert len(result_msgs) > 0


class TestCompactionResult:
    """Tests for CompactionResult dataclass."""

    def test_result_fields(self):
        """Test CompactionResult has all expected fields."""
        result = CompactionResult(
            original_tokens=10000,
            compacted_tokens=3000,
            messages_removed=20,
            messages_preserved=5,
            strategy_used=CompactionStrategy.SUMMARY,
            summary="Test summary",
        )

        assert result.original_tokens == 10000
        assert result.compacted_tokens == 3000
        assert result.messages_removed == 20
        assert result.messages_preserved == 5
        assert result.strategy_used == CompactionStrategy.SUMMARY
        assert result.summary == "Test summary"

    def test_result_without_summary(self):
        """Test CompactionResult with no summary."""
        result = CompactionResult(
            original_tokens=1000,
            compacted_tokens=1000,
            messages_removed=0,
            messages_preserved=5,
            strategy_used=CompactionStrategy.TRUNCATE,
        )

        assert result.summary is None


class TestCreateCompactor:
    """Tests for create_compactor factory function."""

    def test_create_with_defaults(self):
        """Test creating compactor with defaults."""
        from amcp.compaction import create_compactor

        client = MagicMock()
        compactor = create_compactor(client, "gpt-4-turbo")

        assert isinstance(compactor, SmartCompactor)
        assert compactor.config.strategy == CompactionStrategy.SUMMARY

    def test_create_with_custom_strategy(self):
        """Test creating compactor with custom strategy."""
        from amcp.compaction import create_compactor

        client = MagicMock()
        compactor = create_compactor(
            client,
            "gpt-4-turbo",
            strategy="hybrid",
            threshold_ratio=0.8,
            target_ratio=0.4,
        )

        assert compactor.config.strategy == CompactionStrategy.HYBRID
        assert compactor.config.threshold_ratio == 0.8
        assert compactor.config.target_ratio == 0.4
