"""Tests for LLM client abstraction."""

from types import SimpleNamespace

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

    def test_none_config_uses_defaults(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("AMCP_API_TYPE", raising=False)

        client = create_llm_client(None)
        assert isinstance(client, OpenAIClient)


class TestOpenAIClient:
    def test_client_creation(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        assert client.model == "gpt-4o"

    def test_chat_captures_provider_usage(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        client.client.chat.completions.create = lambda **_kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="done", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=30,
                total_tokens=150,
                prompt_tokens_details=SimpleNamespace(cached_tokens=40),
            ),
        )

        response = client.chat([{"role": "user", "content": "hello"}])

        assert response.usage is not None
        assert response.usage.input_tokens == 80
        assert response.usage.prompt_tokens == 120
        assert response.usage.output_tokens == 30
        assert response.usage.total_tokens == 150
        assert response.usage.cached_input_tokens == 40

    def test_chat_uses_reasoning_as_content_when_content_missing(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        client.client.chat.completions.create = lambda **_kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        reasoning_content="DeepSeek final answer",
                        tool_calls=None,
                    ),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

        response = client.chat([{"role": "user", "content": "hello"}])

        assert response.content == "DeepSeek final answer"
        assert response.thinking is None

    def test_chat_keeps_reasoning_hidden_when_content_present(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        client.client.chat.completions.create = lambda **_kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Visible answer",
                        reasoning_content="Hidden reasoning",
                        tool_calls=None,
                    ),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

        response = client.chat([{"role": "user", "content": "hello"}])

        assert response.content == "Visible answer"
        assert response.thinking == "Hidden reasoning"

    def test_streaming_chat_uses_reasoning_as_content_when_content_missing(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        client.client.chat.completions.create = lambda **_kwargs: [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content="Deep",
                            tool_calls=None,
                        ),
                        finish_reason=None,
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content="Seek",
                            tool_calls=None,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            ),
        ]
        streamed_chunks = []

        response = client.chat(
            [{"role": "user", "content": "hello"}],
            stream_callback=streamed_chunks.append,
        )

        assert streamed_chunks == ["DeepSeek"]
        assert response.content == "DeepSeek"
        assert response.thinking is None

    def test_chat_raises_clear_error_when_choices_missing(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        client.client.chat.completions.create = lambda **_kwargs: SimpleNamespace(
            choices=None,
            usage=None,
        )

        with pytest.raises(ValueError, match="without choices"):
            client.chat([{"role": "user", "content": "hello"}])


class TestOpenAIResponsesClient:
    def test_client_creation(self):
        client = OpenAIResponsesClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        assert client.model == "gpt-4o"

    def test_responses_captures_provider_usage(self):
        client = OpenAIResponsesClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-4o")
        client.client.responses.create = lambda **_kwargs: SimpleNamespace(
            output=[],
            stop_reason="stop",
            usage=SimpleNamespace(
                input_tokens=200,
                output_tokens=50,
                total_tokens=250,
                input_tokens_details=SimpleNamespace(cached_tokens=80),
            ),
        )

        response = client.chat([{"role": "user", "content": "hello"}])

        assert response.usage is not None
        assert response.usage.input_tokens == 120
        assert response.usage.prompt_tokens == 200
        assert response.usage.output_tokens == 50
        assert response.usage.cached_input_tokens == 80


class TestAnthropicClient:
    def test_client_creation(self):
        try:
            client = AnthropicClient(api_key="test-key", model="claude-sonnet-4-20250514")
            assert client.model == "claude-sonnet-4-20250514"
        except ImportError:
            pytest.skip("anthropic package not installed")

    def test_anthropic_captures_provider_usage(self):
        client = AnthropicClient.__new__(AnthropicClient)
        client.model = "claude-sonnet-4-20250514"
        client.client = SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    content=[],
                    stop_reason="end_turn",
                    usage=SimpleNamespace(
                        input_tokens=100,
                        output_tokens=20,
                        cache_creation_input_tokens=10,
                        cache_read_input_tokens=30,
                    ),
                )
            )
        )

        response = client.chat([{"role": "user", "content": "hello"}])

        assert response.usage is not None
        assert response.usage.input_tokens == 100
        assert response.usage.prompt_tokens == 140
        assert response.usage.output_tokens == 20
        assert response.usage.cached_input_tokens == 30
        assert response.usage.cache_write_input_tokens == 10
