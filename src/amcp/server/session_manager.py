"""Session manager for AMCP Server.

Manages multiple agent sessions for concurrent client connections.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..agent import Agent
from ..agent_spec import get_default_agent_spec, load_agent_spec
from ..multi_agent import get_agent_registry
from .config import ServerConfig, get_server_config
from .models import Session, SessionStatus, TokenUsage


class SessionNotFoundError(Exception):
    """Raised when a session is not found."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


class SessionBusyError(Exception):
    """Raised when a session is busy."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session is busy: {session_id}")


class MaxSessionsReachedError(Exception):
    """Raised when maximum sessions limit is reached."""

    def __init__(self, max_sessions: int):
        self.max_sessions = max_sessions
        super().__init__(f"Maximum sessions limit reached: {max_sessions}")


class ManagedSession:
    """A managed session with agent and metadata."""

    def __init__(
        self,
        session_id: str,
        agent: Agent,
        cwd: str,
        agent_name: str,
    ):
        self.id = session_id
        self.agent = agent
        self.cwd = cwd
        self.agent_name = agent_name
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.status = SessionStatus.IDLE
        self.message_count = 0
        self.token_usage = TokenUsage()
        self._lock = asyncio.Lock()

    def to_session(self) -> Session:
        """Convert to Session model."""
        return Session(
            id=self.id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            cwd=self.cwd,
            agent_name=self.agent_name,
            status=self.status,
            message_count=self.message_count,
            token_usage=self.token_usage,
            queued_count=self.agent.queued_count(),
        )

    def update_status(self, status: SessionStatus) -> None:
        """Update session status."""
        self.status = status
        self.updated_at = datetime.now()

    def add_token_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Add token usage."""
        self.token_usage.prompt_tokens += prompt_tokens
        self.token_usage.completion_tokens += completion_tokens
        self.token_usage.total_tokens = self.token_usage.prompt_tokens + self.token_usage.completion_tokens
        self.updated_at = datetime.now()


class SessionManager:
    """Manages multiple agent sessions.

    Thread-safe manager for creating, accessing, and destroying sessions.
    Each session maintains its own Agent instance and conversation history.
    """

    def __init__(self, config: ServerConfig | None = None):
        self.config = config or get_server_config()
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = asyncio.Lock()
        self._event_listeners: list[Callable[[str, Any], None]] = []

    @property
    def session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self._sessions)

    async def create_session(
        self,
        cwd: str | None = None,
        agent_name: str | None = None,
        session_id: str | None = None,
    ) -> ManagedSession:
        """Create a new session.

        Args:
            cwd: Working directory for the session. Defaults to config work_dir or cwd.
            agent_name: Name of the agent to use. Defaults to config default_agent.
            session_id: Optional session ID. Auto-generated if not provided.

        Returns:
            The created ManagedSession.

        Raises:
            MaxSessionsReachedError: If maximum sessions limit is reached.
        """
        async with self._lock:
            if len(self._sessions) >= self.config.max_sessions:
                raise MaxSessionsReachedError(self.config.max_sessions)

            # Generate session ID
            if session_id is None:
                session_id = self._generate_session_id()

            # Resolve working directory
            if cwd is None:
                cwd = str(self.config.work_dir or Path.cwd())

            # Resolve agent
            agent_name = agent_name or self.config.default_agent
            agent_spec = self._resolve_agent_spec(agent_name)

            # Create agent instance
            agent = Agent(agent_spec=agent_spec, session_id=session_id)

            # Create managed session
            session = ManagedSession(
                session_id=session_id,
                agent=agent,
                cwd=cwd,
                agent_name=agent_name,
            )

            self._sessions[session_id] = session
            self._emit_event("session.created", {"session_id": session_id})

            return session

    async def get_session(self, session_id: str) -> ManagedSession:
        """Get a session by ID.

        Args:
            session_id: The session ID.

        Returns:
            The ManagedSession.

        Raises:
            SessionNotFoundError: If session is not found.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    async def list_sessions(self) -> list[Session]:
        """List all sessions.

        Returns:
            List of Session models.
        """
        return [s.to_session() for s in self._sessions.values()]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session.

        Args:
            session_id: The session ID.

        Raises:
            SessionNotFoundError: If session is not found.
        """
        async with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)

            del self._sessions[session_id]
            self._emit_event("session.deleted", {"session_id": session_id})

    async def prompt_session(
        self,
        session_id: str,
        content: str,
        work_dir: Path | None = None,
        stream: bool = True,
        priority: str = "normal",
    ):
        """Send a prompt to a session.

        Args:
            session_id: The session ID.
            content: The prompt content.
            work_dir: Optional working directory override.
            stream: Whether to stream the response.
            priority: Message priority.

        Yields:
            Response chunks from the agent.

        Raises:
            SessionNotFoundError: If session is not found.
        """
        session = await self.get_session(session_id)

        # Update status
        session.update_status(SessionStatus.BUSY)
        self._emit_event(
            "session.status_changed",
            {"session_id": session_id, "status": SessionStatus.BUSY.value},
        )

        try:
            # Resolve work directory
            effective_work_dir = work_dir or Path(session.cwd)

            # Map priority string to enum
            from ..message_queue import MessagePriority as MQPriority

            priority_map = {
                "low": MQPriority.LOW,
                "normal": MQPriority.NORMAL,
                "high": MQPriority.HIGH,
                "urgent": MQPriority.URGENT,
            }
            mq_priority = priority_map.get(priority, MQPriority.NORMAL)

            # Run the agent
            async for chunk in session.agent.run(
                user_input=content,
                work_dir=effective_work_dir,
                stream=stream,
                show_progress=False,  # Server doesn't show progress
                priority=mq_priority,
            ):
                yield chunk

            session.message_count += 1
            session.update_status(SessionStatus.IDLE)

        except Exception as e:
            session.update_status(SessionStatus.ERROR)
            self._emit_event(
                "session.error",
                {"session_id": session_id, "error": str(e)},
            )
            raise

        finally:
            self._emit_event(
                "session.status_changed",
                {"session_id": session_id, "status": session.status.value},
            )

    async def cancel_session(self, session_id: str, force: bool = False) -> None:
        """Cancel the current operation in a session.

        Args:
            session_id: The session ID.
            force: Whether to force cancellation.

        Raises:
            SessionNotFoundError: If session is not found.
        """
        session = await self.get_session(session_id)
        session.update_status(SessionStatus.CANCELLED)
        session.agent.clear_queue()

        self._emit_event(
            "session.cancelled",
            {"session_id": session_id, "force": force},
        )

    def add_event_listener(self, listener: Callable[[str, Any], None]) -> None:
        """Add an event listener.

        Args:
            listener: Callback function receiving (event_type, payload).
        """
        self._event_listeners.append(listener)

    def remove_event_listener(self, listener: Callable[[str, Any], None]) -> None:
        """Remove an event listener.

        Args:
            listener: The listener to remove.
        """
        if listener in self._event_listeners:
            self._event_listeners.remove(listener)

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit an event to all listeners.

        Args:
            event_type: Type of event.
            payload: Event payload.
        """
        for listener in self._event_listeners:
            try:
                listener(event_type, payload)
            except Exception:
                pass  # Don't let listener errors affect the manager

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return f"session-{uuid.uuid4().hex[:12]}"

    def _resolve_agent_spec(self, agent_name: str):
        """Resolve agent specification by name.

        Args:
            agent_name: Name of the agent.

        Returns:
            Resolved agent specification.
        """
        # Try to get from registry
        registry = get_agent_registry()
        agent_config = registry.get(agent_name)

        if agent_config:
            # Create a ResolvedAgentSpec from AgentConfig
            from ..agent_spec import ResolvedAgentSpec, AgentMode as SpecAgentMode

            # Map multi_agent AgentMode to agent_spec AgentMode
            mode_map = {
                "primary": SpecAgentMode.PRIMARY,
                "subagent": SpecAgentMode.SUBAGENT,
            }
            spec_mode = mode_map.get(agent_config.mode.value, SpecAgentMode.PRIMARY)

            return ResolvedAgentSpec(
                name=agent_config.name,
                description=agent_config.description,
                mode=spec_mode,
                system_prompt=agent_config.system_prompt,
                max_steps=agent_config.max_steps,
                tools=agent_config.tools,
            )

        # Fall back to default
        return get_default_agent_spec()


# Global session manager instance
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get the global session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def set_session_manager(manager: SessionManager) -> None:
    """Set the global session manager."""
    global _session_manager
    _session_manager = manager


def reset_session_manager() -> None:
    """Reset the global session manager."""
    global _session_manager
    _session_manager = None
