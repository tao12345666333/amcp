"""LLM client abstraction supporting OpenAI, OpenAI Responses, and Anthropic APIs."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .config import ChatConfig


def _extract_think_tags(content: str) -> tuple[str | None, str]:
    """Extract content from <think> tags and return (thinking, remaining_content)."""
    pattern = r"<think>(.*?)</think>"
    matches = re.findall(pattern, content, re.DOTALL)
    if matches:
        thinking = "\n".join(m.strip() for m in matches)
        remaining = re.sub(pattern, "", content, flags=re.DOTALL).strip()
        return thinking, remaining
    return None, content


@dataclass
class LLMResponse:
    """Unified response from LLM."""

    content: str | None
    tool_calls: list[dict[str, Any]] | None = None
    stop_reason: str | None = None
    thinking: str | None = None  # Reasoning/thinking content from LLM


class BaseLLMClient(ABC):
    """Base class for LLM clients."""

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        """Send chat request and return response."""
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI Chat Completions API client."""

    def __init__(self, base_url: str, api_key: str | None, model: str):
        from openai import OpenAI

        self.client = OpenAI(base_url=base_url, api_key=api_key or "")
        self.model = model

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        params = {"model": self.model, "messages": messages, "stream": False, **kwargs}
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        resp = self.client.chat.completions.create(**params)
        msg = resp.choices[0].message

        tool_calls = None
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments} for tc in msg.tool_calls
            ]

        # Extract thinking content
        thinking = None
        content = msg.content

        # Check for reasoning_content field (DeepSeek, some OpenAI-compatible APIs)
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            thinking = msg.reasoning_content
        # Check for <think> tags in content
        elif content:
            thinking, content = _extract_think_tags(content)

        return LLMResponse(
            content=content, tool_calls=tool_calls, stop_reason=resp.choices[0].finish_reason, thinking=thinking
        )


class OpenAIResponsesClient(BaseLLMClient):
    """OpenAI Responses API client."""

    def __init__(self, base_url: str, api_key: str | None, model: str):
        from openai import OpenAI

        self.client = OpenAI(base_url=base_url, api_key=api_key or "")
        self.model = model

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
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

        params = {"model": self.model, "input": messages}
        if resp_tools:
            params["tools"] = resp_tools

        resp = self.client.responses.create(**params)

        # Parse response
        content_parts = []
        tool_calls = []

        for item in resp.output:
            if item.type == "message":
                for block in item.content:
                    if block.type == "output_text":
                        content_parts.append(block.text)
            elif item.type == "function_call":
                tool_calls.append({"id": item.call_id, "name": item.name, "arguments": item.arguments})

        return LLMResponse(
            content="\n".join(content_parts) if content_parts else None,
            tool_calls=tool_calls if tool_calls else None,
            stop_reason=resp.stop_reason,
        )


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API client."""

    def __init__(self, api_key: str | None, model: str, base_url: str | None = None):
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic") from None

        kwargs = {"api_key": api_key or os.environ.get("ANTHROPIC_API_KEY", "")}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = Anthropic(**kwargs)
        self.model = model

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        # Convert OpenAI format to Anthropic format
        system_prompt = None
        anthropic_messages = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content
            elif role == "user":
                anthropic_messages.append({"role": "user", "content": content})
            elif role == "assistant":
                if msg.get("tool_calls"):
                    blocks = []
                    if content:
                        blocks.append({"type": "text", "text": content})
                    for tc in msg["tool_calls"]:
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "input": json.loads(tc["function"]["arguments"] or "{}"),
                            }
                        )
                    anthropic_messages.append({"role": "assistant", "content": blocks})
                else:
                    anthropic_messages.append({"role": "assistant", "content": content})
            elif role == "tool":
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": msg.get("tool_call_id"), "content": content}
                        ],
                    }
                )

        # Convert tools to Anthropic format
        anthropic_tools = None
        if tools:
            anthropic_tools = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]

        params = {"model": self.model, "messages": anthropic_messages, "max_tokens": kwargs.get("max_tokens", 4096)}
        if system_prompt:
            params["system"] = system_prompt
        if anthropic_tools:
            params["tools"] = anthropic_tools

        resp = self.client.messages.create(**params)

        content_parts = []
        tool_calls = []
        thinking_parts = []

        for block in resp.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "thinking":
                # Anthropic extended thinking block
                thinking_parts.append(getattr(block, "thinking", ""))
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "arguments": json.dumps(block.input)})

        return LLMResponse(
            content="\n".join(content_parts) if content_parts else None,
            tool_calls=tool_calls if tool_calls else None,
            stop_reason=resp.stop_reason,
            thinking="\n".join(thinking_parts) if thinking_parts else None,
        )


def create_llm_client(cfg: ChatConfig | None) -> BaseLLMClient:
    """Create appropriate LLM client based on config.

    api_type options:
    - "openai" (default): OpenAI Chat Completions API
    - "openai_responses": OpenAI Responses API
    - "anthropic": Anthropic Claude API
    """
    api_type = (cfg.api_type if cfg else None) or os.environ.get("AMCP_API_TYPE", "openai")
    model = (cfg.model if cfg else None) or "gpt-4o"

    if api_type == "anthropic":
        api_key = (cfg.api_key if cfg else None) or os.environ.get("ANTHROPIC_API_KEY")
        base_url = cfg.base_url if cfg else None
        return AnthropicClient(api_key=api_key, model=model, base_url=base_url)
    elif api_type == "openai_responses":
        base_url = (cfg.base_url if cfg else None) or os.environ.get("AMCP_OPENAI_BASE", "https://api.openai.com/v1")
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        api_key = (cfg.api_key if cfg else None) or os.environ.get("OPENAI_API_KEY")
        return OpenAIResponsesClient(base_url=base_url, api_key=api_key, model=model)
    else:
        # Default: OpenAI Chat Completions
        base_url = (cfg.base_url if cfg else None) or os.environ.get("AMCP_OPENAI_BASE", "https://api.openai.com/v1")
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        api_key = (cfg.api_key if cfg else None) or os.environ.get("OPENAI_API_KEY")
        return OpenAIClient(base_url=base_url, api_key=api_key, model=model)
