from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..client.base import BaseClient, ResponseChunk
from ..client.embedded import EmbeddedClient
from .bot import TelegramBot


class TelegramClient(BaseClient):
    """Telegram client that runs a bot alongside an embedded client."""

    def __init__(self, bot: TelegramBot) -> None:
        self._bot = bot
        self._embedded = EmbeddedClient()
        self._connected = False
        self._polling_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        await self._embedded.connect()
        self._polling_task = asyncio.create_task(self._bot.start_polling())
        self._connected = True

    async def close(self) -> None:
        await self._bot.stop()
        if self._polling_task:
            await self._polling_task
        await self._embedded.close()
        self._connected = False

    async def health(self) -> dict[str, Any]:
        return await self._embedded.health()

    async def info(self) -> dict[str, Any]:
        return await self._embedded.info()

    async def create_session(
        self,
        *,
        cwd: str | None = None,
        agent_name: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._embedded.create_session(
            cwd=cwd,
            agent_name=agent_name,
            session_id=session_id,
        )

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return await self._embedded.get_session(session_id)

    async def list_sessions(self) -> list[dict[str, Any]]:
        return await self._embedded.list_sessions()

    async def delete_session(self, session_id: str) -> None:
        await self._embedded.delete_session(session_id)

    async def prompt(
        self,
        session_id: str,
        content: str,
        *,
        stream: bool = True,
        priority: str = "normal",
    ) -> str | AsyncIterator[ResponseChunk]:
        return await self._embedded.prompt(
            session_id=session_id,
            content=content,
            stream=stream,
            priority=priority,
        )
