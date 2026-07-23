"""Unified LLM client abstraction built on any-llm."""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, cast

from .config import ChatConfig

# Type aliases for commonly used complex types
ToolCall = dict[str, Any]
Message = dict[str, Any]


def _extract_think_tags(content: str) -> tuple[str | None, str]:
    """Extract content from <think> tags and return (thinking, remaining_content)."""
    pattern = r"<think>(.*?)</think>"
    matches = re.findall(pattern, content, re.DOTALL)
    if matches:
        thinking = "\n".join(m.strip() for m in matches)
        remaining = re.sub(pattern, "", content, flags=re.DOTALL).strip()
        return thinking, remaining
    return None, content


def _response_field(value: Any, name: str, default: Any = None) -> Any:
    """Read a field from SDK objects or dictionaries."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _first_chat_choice(response: Any) -> Any:
    """Return the first chat-completions choice or raise a clear provider error."""
    choices = _response_field(response, "choices")
    if not choices:
        raise ValueError(
            "Provider returned a chat completion response without choices. "
            "Check that api_type, base_url, and model match the provider's supported API."
        )
    return choices[0]


def _split_response_content(
    content: str | None,
    reasoning_content: str | None,
    *,
    allow_reasoning_as_content: bool,
) -> tuple[str | None, str | None]:
    """Split provider content into user-visible content and hidden thinking."""
    thinking_from_content = None
    if content:
        thinking_from_content, content = _extract_think_tags(content)

    if reasoning_content and not content and allow_reasoning_as_content:
        return thinking_from_content, reasoning_content

    if reasoning_content:
        if thinking_from_content:
            reasoning_content = "\n".join([reasoning_content, thinking_from_content])
        return reasoning_content, content

    return thinking_from_content, content


def _reasoning_content(value: Any) -> str | None:
    """Read normalized any-llm reasoning, with legacy provider fallback."""
    reasoning = _response_field(value, "reasoning")
    if isinstance(reasoning, str):
        return reasoning
    if reasoning is not None:
        content = _response_field(reasoning, "content")
        if content:
            return str(content)
    legacy = _response_field(value, "reasoning_content")
    return str(legacy) if legacy else None


@dataclass
class TokenUsage:
    """Normalized token usage returned by an LLM provider."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """Return all tokens occupying the input context."""
        return self.input_tokens + self.cached_input_tokens + self.cache_write_input_tokens


@dataclass
class LLMResponse:
    """Unified response from LLM."""

    content: str | None
    tool_calls: list[ToolCall] | None = None
    stop_reason: str | None = None
    thinking: str | None = None  # Reasoning/thinking content from LLM
    usage: TokenUsage | None = None


def _usage_value(usage: Any, name: str) -> int:
    """Read an integer usage field from SDK objects or dictionaries."""
    if usage is None:
        return 0
    value = usage.get(name, 0) if isinstance(usage, dict) else getattr(usage, name, 0)
    return int(value or 0)


def _usage_details_value(usage: Any, details_name: str, value_name: str) -> int:
    """Read a nested usage detail from SDK objects or dictionaries."""
    if usage is None:
        return 0
    details = usage.get(details_name) if isinstance(usage, dict) else getattr(usage, details_name, None)
    return _usage_value(details, value_name)


def _openai_chat_usage(usage: Any) -> TokenUsage | None:
    """Normalize Chat Completions usage."""
    if usage is None:
        return None
    prompt_tokens = _usage_value(usage, "prompt_tokens")
    output_tokens = _usage_value(usage, "completion_tokens")
    cache_read = _usage_details_value(usage, "prompt_tokens_details", "cached_tokens")
    cache_write = _usage_details_value(usage, "prompt_tokens_details", "cache_write_tokens")
    input_tokens = max(0, prompt_tokens - cache_read - cache_write)
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=_usage_value(usage, "total_tokens") or prompt_tokens + output_tokens,
        cached_input_tokens=cache_read,
        cache_write_input_tokens=cache_write,
    )


def _responses_usage(usage: Any) -> TokenUsage | None:
    """Normalize OpenAI Responses API usage."""
    if usage is None:
        return None
    provider_input_tokens = _usage_value(usage, "input_tokens")
    output_tokens = _usage_value(usage, "output_tokens")
    cache_read = _usage_details_value(usage, "input_tokens_details", "cached_tokens")
    input_tokens = max(0, provider_input_tokens - cache_read)
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=_usage_value(usage, "total_tokens") or provider_input_tokens + output_tokens,
        cached_input_tokens=cache_read,
    )


class BaseLLMClient(ABC):
    """Base class for LLM clients."""

    model: str  # Model name/identifier

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[Message] | None = None,
        stream_callback: Any | None = None,  # Callable[[str], None]
        **kwargs,
    ) -> LLMResponse:
        """Send chat request and return response."""
        pass


class AnyLLMClient(BaseLLMClient):
    """Completion client for any provider supported by any-llm."""

    def __init__(
        self,
        provider: str,
        base_url: str | None,
        api_key: str | None,
        model: str,
    ):
        from any_llm import AnyLLM

        self.client = AnyLLM.create(provider, api_key=api_key, api_base=base_url)
        self.provider = provider
        self.model = model

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream_callback: Any | None = None,
        **kwargs,
    ) -> LLMResponse:
        model = kwargs.pop("model", self.model)
        callback = stream_callback
        stream = callback is not None
        params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "allow_running_loop": True,
            **kwargs,
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        if stream:
            assert callback is not None
            # Streaming mode
            accumulated_content = []
            accumulated_reasoning = []
            tool_calls_chunks = {}  # index -> accumulated chunk
            finish_reason = None
            usage = None

            response = self.client.completion(**params)

            for chunk in response:
                chunk_usage = _response_field(chunk, "usage")
                if chunk_usage is not None:
                    usage = _openai_chat_usage(chunk_usage)
                # Some APIs (e.g., DeepSeek) may return chunks with empty choices
                choices = _response_field(chunk, "choices")
                if not choices:
                    continue
                delta = _response_field(choices[0], "delta")
                finish_reason = _response_field(choices[0], "finish_reason")

                # Handle content
                delta_content = _response_field(delta, "content")
                if delta_content:
                    callback(delta_content)
                    accumulated_content.append(delta_content)

                # Handle thinking (if present in specific fields)
                delta_reasoning = _reasoning_content(delta)
                if delta_reasoning:
                    accumulated_reasoning.append(delta_reasoning)

                # Handle tool calls (accumulate them)
                delta_tool_calls = _response_field(delta, "tool_calls")
                if delta_tool_calls:
                    for tc in delta_tool_calls:
                        idx = _response_field(tc, "index", 0)
                        if idx not in tool_calls_chunks:
                            tool_calls_chunks[idx] = {"id": "", "name": "", "arguments": ""}

                        tool_call_id = _response_field(tc, "id")
                        if tool_call_id:
                            tool_calls_chunks[idx]["id"] += tool_call_id
                        function = _response_field(tc, "function")
                        if function:
                            name = _response_field(function, "name")
                            arguments = _response_field(function, "arguments")
                            if name:
                                tool_calls_chunks[idx]["name"] += name
                            if arguments:
                                tool_calls_chunks[idx]["arguments"] += arguments

            # Reconstruct full response
            content = "".join(accumulated_content) if accumulated_content else None
            reasoning_text = "".join(accumulated_reasoning) if accumulated_reasoning else None

            tool_calls = []
            if tool_calls_chunks:
                for idx in sorted(tool_calls_chunks.keys()):
                    tc = tool_calls_chunks[idx]
                    tool_calls.append({"id": tc["id"], "name": tc["name"], "arguments": tc["arguments"]})

            if reasoning_text and not content and not tool_calls:
                callback(reasoning_text)

            thinking, content = _split_response_content(
                content,
                reasoning_text,
                allow_reasoning_as_content=not tool_calls,
            )

            return LLMResponse(
                content=content,
                tool_calls=tool_calls if tool_calls else None,
                stop_reason=finish_reason,
                thinking=thinking,
                usage=usage,
            )

        else:
            resp = self.client.completion(**params)
            first_choice = _first_chat_choice(resp)
            msg = _response_field(first_choice, "message")
            if msg is None:
                raise ValueError("Provider returned a chat completion choice without a message.")

            tool_calls = None
            message_tool_calls = _response_field(msg, "tool_calls")
            if message_tool_calls:
                tool_calls = [
                    {
                        "id": _response_field(tc, "id"),
                        "name": _response_field(_response_field(tc, "function"), "name"),
                        "arguments": _response_field(_response_field(tc, "function"), "arguments", "{}"),
                    }
                    for tc in message_tool_calls
                ]

            # Extract thinking content
            thinking, content = _split_response_content(
                _response_field(msg, "content"),
                _reasoning_content(msg),
                allow_reasoning_as_content=tool_calls is None,
            )

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                stop_reason=_response_field(first_choice, "finish_reason"),
                thinking=thinking,
                usage=_openai_chat_usage(_response_field(resp, "usage")),
            )


class OpenAIClient(AnyLLMClient):
    """Backward-compatible OpenAI completion client."""

    def __init__(self, base_url: str, api_key: str | None, model: str):
        super().__init__("openai", base_url, api_key, model)


class AnthropicClient(AnyLLMClient):
    """Backward-compatible Anthropic completion client."""

    def __init__(self, api_key: str | None, model: str, base_url: str | None = None):
        super().__init__("anthropic", base_url, api_key, model)


class OpenAIResponsesClient(BaseLLMClient):
    """OpenAI Responses API client backed by any-llm."""

    def __init__(self, base_url: str, api_key: str | None, model: str):
        from any_llm import AnyLLM

        self.client = AnyLLM.create("openai", api_key=api_key, api_base=base_url)
        self.model = model

    def chat(
        self,
        messages: list[Message],
        tools: list[Message] | None = None,
        stream_callback: Any | None = None,
        **kwargs,
    ) -> LLMResponse:
        # Convert tools to Responses API format
        resp_tools = None
        if tools:
            resp_tools = [
                {
                    "type": "function",
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "parameters": t["function"].get("parameters", {}),
                }
                for t in tools
            ]

        model = kwargs.pop("model", self.model)
        max_tokens = kwargs.pop("max_tokens", None)
        params: dict[str, Any] = {
            "model": model,
            "input_data": cast(Any, self._convert_messages(messages)),
            "tools": resp_tools,
            "allow_running_loop": True,
            **kwargs,
        }
        if max_tokens is not None:
            params["max_output_tokens"] = max_tokens

        if stream_callback:
            completed_response = None
            for event in self.client.responses(stream=True, **params):
                event_type = _response_field(event, "type")
                if event_type == "response.output_text.delta":
                    delta = _response_field(event, "delta")
                    if delta:
                        stream_callback(delta)
                elif event_type == "response.completed":
                    completed_response = _response_field(event, "response")
            if completed_response is None:
                raise ValueError("Provider response stream ended without a completed response.")
            return self._parse_response(completed_response)

        resp = self.client.responses(**params)
        return self._parse_response(resp)

    @staticmethod
    def _convert_messages(messages: list[Message]) -> list[Message]:
        """Convert AMCP Chat Completions history to Responses input items."""
        converted: list[Message] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                converted.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.get("tool_call_id"),
                        "output": message.get("content", ""),
                    }
                )
                continue

            message_tool_calls = message.get("tool_calls")
            if role == "assistant" and message_tool_calls:
                if message.get("content"):
                    converted.append({"role": "assistant", "content": message["content"]})
                for tool_call in message_tool_calls:
                    function = tool_call.get("function", {})
                    converted.append(
                        {
                            "type": "function_call",
                            "call_id": tool_call.get("id"),
                            "name": function.get("name"),
                            "arguments": function.get("arguments", "{}"),
                        }
                    )
                continue

            converted.append({"role": role, "content": message.get("content", "")})
        return converted

    @staticmethod
    def _parse_response(resp: Any) -> LLMResponse:
        """Normalize an any-llm Responses result."""

        # Parse response
        content_parts = []
        tool_calls = []

        for item in _response_field(resp, "output", []):
            if _response_field(item, "type") == "message":
                for block in _response_field(item, "content", []):
                    if _response_field(block, "type") == "output_text":
                        content_parts.append(_response_field(block, "text", ""))
            elif _response_field(item, "type") == "function_call":
                tool_calls.append(
                    {
                        "id": _response_field(item, "call_id"),
                        "name": _response_field(item, "name"),
                        "arguments": _response_field(item, "arguments", "{}"),
                    }
                )

        return LLMResponse(
            content="\n".join(content_parts) if content_parts else None,
            tool_calls=tool_calls if tool_calls else None,
            stop_reason=_response_field(resp, "stop_reason") or _response_field(resp, "status"),
            usage=_responses_usage(_response_field(resp, "usage")),
        )


def create_llm_client(cfg: ChatConfig | None) -> BaseLLMClient:
    """Create an any-llm client based on config.

    api_type options:
    - Any any-llm provider ID, such as "openai", "anthropic", or "gmi"
    - "openai_responses": OpenAI Responses API
    """
    api_type = (cfg.api_type if cfg else None) or os.environ.get("AMCP_API_TYPE", "openai")
    model = (cfg.model if cfg else None) or "gpt-5.5"

    if api_type == "openai_responses":
        responses_base_url = (cfg.base_url if cfg else None) or os.environ.get(
            "AMCP_OPENAI_BASE", "https://api.openai.com/v1"
        )
        api_key = (cfg.api_key if cfg else None) or os.environ.get("OPENAI_API_KEY")
        return OpenAIResponsesClient(
            base_url=responses_base_url,
            api_key=api_key,
            model=model,
        )

    base_url: str | None = cfg.base_url if cfg else None
    if api_type == "openai":
        base_url = base_url or os.environ.get("AMCP_OPENAI_BASE", "https://api.openai.com/v1")
    api_key = cfg.api_key if cfg else None
    if api_type == "openai":
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
    elif api_type == "gmi":
        api_key = api_key or os.environ.get("GMI_API_KEY") or os.environ.get("OPENAI_API_KEY")

    if api_type == "openai":
        assert base_url is not None
        return OpenAIClient(base_url=base_url, api_key=api_key, model=model)
    if api_type == "anthropic":
        return AnthropicClient(base_url=base_url, api_key=api_key, model=model)
    return AnyLLMClient(
        provider=api_type,
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
