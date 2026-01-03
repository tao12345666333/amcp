"""Tests for LLM client abstraction."""

import pytest

from amcp.config import ChatConfig
from amcp.llm import AnthropicClient, LLMResponse, OpenAIClient, OpenAIResponsesClient, create_llm_client


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_basic_response(self):
        resp = LLMResponse(content="Hello, world!")
        assert resp.content == "Hello, world!"
        assert resp.tool_calls is None

    def test_response_with_tool_calls(self):
        tool_calls = [{"id": "1", "name": "test", "arguments": "{}"}]
        resp = LLMResponse(content=None, tool_calls=tool_calls, stop_reason="tool_use")
        assert resp.tool_calls == tool_calls


class TestCreateLLMClient:
    """Tests for create_llm_client factory."""

    def test_default_creates_openai_client(self):
        cfg = ChatConfig(model="gpt-4o", api_key="test-key")
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAIClient)

    def test_openai_type_creates_openai_client(self):
        cfg = ChatConfig(api_type="openai", model="gpt-4o", api_key="test-key")
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAIClient)

    def test_openai_responses_type(self):
        cfg = ChatConfig(api_type="openai_responses", model="gpt-4o", api_key="test-key")
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAIResponsesClient)

    def test_anthropic_type(self):
        try:
            cfg = ChatConfig(api_type="anthropic", model="claude-sonnet-4-20250514", api_key="test-key")
            client = create_llm_client(cfg)
            assert isinstance(client, AnthropicClient)
        except ImportError:
            pytest.skip("anthropic package not installed")

    def test_none_config_uses_defaults(self):
        client = create_llm_client(None)
        assert isinstance(client, OpenAIClient)


class TestOpenAIClient:
    def test_client_creation(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        assert client.model == "gpt-4o"


class TestOpenAIResponsesClient:
    def test_client_creation(self):
        client = OpenAIResponsesClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        assert client.model == "gpt-4o"


class TestAnthropicClient:
    def test_client_creation(self):
        try:
            client = AnthropicClient(api_key="test-key", model="claude-sonnet-4-20250514")
            assert client.model == "claude-sonnet-4-20250514"
        except ImportError:
            pytest.skip("anthropic package not installed")
