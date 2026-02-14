"""Telegram integration for AMCP.

Provides a Telegram Bot interface for remote interaction with AMCP agents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import TelegramConfig

if TYPE_CHECKING:
    from .bot import TelegramBot
    from .client import TelegramClient

__all__ = ["TelegramBot", "TelegramClient", "TelegramConfig"]


def __getattr__(name: str):
    if name == "TelegramBot":
        from .bot import TelegramBot

        return TelegramBot
    if name == "TelegramClient":
        from .client import TelegramClient

        return TelegramClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
