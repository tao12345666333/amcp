"""Session wrapper for AMCP client.

Provides a high-level interface for interacting with a specific session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from .base import ResponseChunk

if TYPE_CHECKING:
    from .base import BaseClient


class ClientSession:
    """High-level wrapper for a session.

    Provides convenient methods for interacting with a session.

    Example:
        session = await client.create_session(cwd="/my/project")
        async for chunk in session.prompt("Hello"):
            print(chunk.content)
    """

    def __init__(
        self,
        client: BaseClient,
        session_id: str,
        *,
        cwd: str | None = None,
        agent_name: str | None = None,
    ):
        """Initialize the session wrapper.

        Args:
            client: The underlying client.
            session_id: The session ID.
            cwd: Working directory for the session.
            agent_name: Agent name for the session.
        """
        self._client = client
        self._session_id = session_id
        self._cwd = cwd
        self._agent_name = agent_name

    @property
    def session_id(self) -> str:
        """Get the session ID."""
        return self._session_id

    @property
    def id(self) -> str:
        """Alias for session_id."""
        return self._session_id

    @property
    def cwd(self) -> str | None:
        """Get the working directory."""
        return self._cwd

    @property
    def agent_name(self) -> str | None:
        """Get the agent name."""
        return self._agent_name

    async def refresh(self) -> ClientSession:
        """Refresh session data from server.

        Returns:
            Updated session wrapper.
        """
        data = await self._client.get_session(self._session_id)
        self._cwd = data.get("cwd")
        self._agent_name = data.get("agent_name")
        return self

    async def info(self) -> dict[str, Any]:
        """Get detailed session information.

        Returns:
            Session data dictionary.
        """
        return await self._client.get_session(self._session_id)

    async def delete(self) -> None:
        """Delete this session."""
        await self._client.delete_session(self._session_id)

    async def prompt(
        self,
        content: str,
        *,
        stream: bool = True,
        priority: str = "normal",
    ) -> str | AsyncIterator[ResponseChunk]:
        """Send a prompt to this session.

        Args:
            content: The prompt content.
            stream: Whether to stream the response.
            priority: Message priority.

        Returns:
            If stream=False, returns the complete response string.
            If stream=True, returns an async iterator of ResponseChunks.

        Examples:
            # Streaming (default)
            async for chunk in session.prompt("Hello"):
                print(chunk.content, end="")

            # Non-streaming
            response = await session.prompt("Hello", stream=False)
            print(response)
        """
        return await self._client.prompt(
            self._session_id,
            content,
            stream=stream,
            priority=priority,
        )

    async def prompt_full(
        self,
        content: str,
        *,
        priority: str = "normal",
    ) -> str:
        """Send a prompt and get the full response.

        Convenience method that always returns the complete response.

        Args:
            content: The prompt content.
            priority: Message priority.

        Returns:
            Complete response string.
        """
        result = await self._client.prompt(
            self._session_id,
            content,
            stream=False,
            priority=priority,
        )
        # Ensure we return a string
        if isinstance(result, str):
            return result
        # If it's an iterator somehow, collect it
        chunks = []
        async for chunk in result:  # type: ignore
            chunks.append(chunk.content)
        return "".join(chunks)

    async def prompt_stream(
        self,
        content: str,
        *,
        priority: str = "normal",
    ) -> AsyncIterator[ResponseChunk]:
        """Send a prompt and stream the response.

        Convenience method that always streams.

        Args:
            content: The prompt content.
            priority: Message priority.

        Yields:
            ResponseChunk objects.
        """
        result = await self._client.prompt(
            self._session_id,
            content,
            stream=True,
            priority=priority,
        )
        # Result should be an async iterator
        if isinstance(result, str):
            # Wrap in a single chunk if string
            yield ResponseChunk(content=result, done=True)
        else:
            async for chunk in result:
                yield chunk

    async def cancel(self, *, force: bool = False) -> None:
        """Cancel the current operation.

        Args:
            force: Whether to force cancellation.
        """
        await self._client.cancel(self._session_id, force=force)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to session events.

        Yields:
            Event dictionaries.

        Note:
            This requires WebSocket support. Use AMCPClient.websocket_session()
            for event streaming.
        """
        # This is a placeholder - actual implementation would need
        # SSE or WebSocket support
        raise NotImplementedError("Event streaming requires WebSocket. Use AMCPClient.websocket_session()")

    def __repr__(self) -> str:
        """Return string representation."""
        return f"ClientSession(id={self._session_id!r}, agent={self._agent_name!r})"
