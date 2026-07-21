"""Tests for LLM client abstraction."""

from types import SimpleNamespace

import pytest
from any_llm.types.completion import Reasoning

from amcp.config import ChatConfig
from amcp.llm import (
    AnthropicClient,
    AnyLLMClient,
    LLMResponse,
    OpenAIClient,
    OpenAIResponsesClient,
    create_llm_client,
)


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
        cfg = ChatConfig(model="gpt-5.5", api_key="test-key")
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAIClient)

    def test_openai_type_creates_openai_client(self):
        cfg = ChatConfig(api_type="openai", model="gpt-5.5", api_key="test-key")
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAIClient)

    def test_openai_responses_type(self):
        cfg = ChatConfig(api_type="openai_responses", model="gpt-5.5", api_key="test-key")
        client = create_llm_client(cfg)
        assert isinstance(client, OpenAIResponsesClient)

    def test_anthropic_type(self):
        cfg = ChatConfig(api_type="anthropic", model="claude-sonnet-4-20250514", api_key="test-key")
        client = create_llm_client(cfg)
        assert isinstance(client, AnthropicClient)

    def test_any_llm_provider_type(self):
        cfg = ChatConfig(api_type="gmi", model="zai-org/GLM-5.2-FP8", api_key="test-key")
        client = create_llm_client(cfg)
        assert isinstance(client, AnyLLMClient)
        assert client.provider == "gmi"

    def test_none_config_uses_defaults(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("AMCP_API_TYPE", raising=False)

        client = create_llm_client(None)
        assert isinstance(client, OpenAIClient)


class TestOpenAIClient:
    def test_client_creation(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5.5")
        assert client.model == "gpt-5.5"

    def test_chat_captures_provider_usage(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5.5")
        client.client.completion = lambda **_kwargs: SimpleNamespace(
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
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5.5")
        client.client.completion = lambda **_kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        reasoning=Reasoning(content="DeepSeek final answer"),
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
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5.5")
        client.client.completion = lambda **_kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Visible answer",
                        reasoning=Reasoning(content="Hidden reasoning"),
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
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5.5")
        client.client.completion = lambda **_kwargs: iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                reasoning=Reasoning(content="Deep"),
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
                                reasoning=Reasoning(content="Seek"),
                                tool_calls=None,
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=None,
                ),
            ]
        )
        streamed_chunks = []

        response = client.chat(
            [{"role": "user", "content": "hello"}],
            stream_callback=streamed_chunks.append,
        )

        assert streamed_chunks == ["DeepSeek"]
        assert response.content == "DeepSeek"
        assert response.thinking is None

    def test_chat_raises_clear_error_when_choices_missing(self):
        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5.5")
        client.client.completion = lambda **_kwargs: SimpleNamespace(
            choices=None,
            usage=None,
        )

        with pytest.raises(ValueError, match="without choices"):
            client.chat([{"role": "user", "content": "hello"}])


class TestOpenAIResponsesClient:
    def test_client_creation(self):
        client = OpenAIResponsesClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5.5")
        assert client.model == "gpt-5.5"

    def test_responses_captures_provider_usage(self):
        client = OpenAIResponsesClient(base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5.5")
        client.client.responses = lambda **_kwargs: SimpleNamespace(
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

    def test_responses_converts_tool_history(self):
        messages = [
            {"role": "user", "content": "read it"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "contents"},
        ]

        converted = OpenAIResponsesClient._convert_messages(messages)

        assert converted == [
            {"role": "user", "content": "read it"},
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "read_file",
                "arguments": '{"path":"a.py"}',
            },
            {"type": "function_call_output", "call_id": "call-1", "output": "contents"},
        ]

    def test_responses_streams_and_forwards_options(self):
        client = OpenAIResponsesClient.__new__(OpenAIResponsesClient)
        client.model = "gpt-5.5"
        captured = {}
        completed = SimpleNamespace(output=[], status="completed", usage=None)

        def responses(**kwargs):
            captured.update(kwargs)
            return iter(
                [
                    SimpleNamespace(type="response.output_text.delta", delta="done"),
                    SimpleNamespace(type="response.completed", response=completed),
                ]
            )

        client.client = SimpleNamespace(responses=responses)
        chunks = []

        response = client.chat(
            [{"role": "user", "content": "hello"}],
            stream_callback=chunks.append,
            model="gpt-5",
            max_tokens=123,
            temperature=0.2,
        )

        assert chunks == ["done"]
        assert response.stop_reason == "completed"
        assert captured["model"] == "gpt-5"
        assert captured["max_output_tokens"] == 123
        assert captured["temperature"] == 0.2
        assert captured["stream"] is True
        assert captured["allow_running_loop"] is True


class TestAnthropicClient:
    def test_client_creation(self):
        client = AnthropicClient(api_key="test-key", model="claude-sonnet-4-20250514")
        assert client.model == "claude-sonnet-4-20250514"

    def test_anthropic_uses_normalized_any_llm_usage(self):
        client = AnthropicClient.__new__(AnthropicClient)
        client.model = "claude-sonnet-4-20250514"
        client.provider = "anthropic"
        client.client = SimpleNamespace(
            completion=lambda **_kwargs: SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="done", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=140,
                    completion_tokens=20,
                    total_tokens=160,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=30),
                ),
            )
        )

        response = client.chat([{"role": "user", "content": "hello"}])

        assert response.usage is not None
        assert response.usage.input_tokens == 110
        assert response.usage.prompt_tokens == 140
        assert response.usage.output_tokens == 20
        assert response.usage.cached_input_tokens == 30
