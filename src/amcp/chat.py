"""Shared OpenAI-compatible chat client helpers."""

from __future__ import annotations

import os

from .config import ChatConfig
from .llm import AnyLLMClient


def _resolve_base_url(cli_base: str | None, cfg: ChatConfig | None) -> str:
    # CLI > config > env > default
    return (
        cli_base
        or (cfg.base_url if cfg and cfg.base_url else None)
        or os.environ.get("AMCP_OPENAI_BASE")
        or "https://api.gmi-serving.com/v1"
    )


def _resolve_api_key(cli_key: str | None, cfg: ChatConfig | None) -> str | None:
    # CLI > config > env
    if cli_key:
        return cli_key
    if cfg and cfg.api_key:
        return cfg.api_key
    return os.environ.get("OPENAI_API_KEY")


def _make_client(
    base_url: str,
    api_key: str | None,
    *,
    provider: str = "openai",
    model: str = "gpt-5.5",
) -> AnyLLMClient:
    """Create the shared any-llm completion client."""
    return AnyLLMClient(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
