"""Application-level dependencies used by agent execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .memory import MemoryManager, get_memory_manager
from .multi_agent import AgentRegistry, get_agent_registry
from .session_search import TranscriptStore, get_transcript_store
from .skills import SkillManager, get_skill_manager
from .tools import ToolRegistry, get_tool_registry


class TranscriptStoreService(Protocol):
    """Transcript operation required by the agent path."""

    def append_turn(
        self,
        *,
        session_id: str,
        user: str,
        assistant: str,
        source: str = "agent",
        chat_id: str | None = None,
        metadata: dict[Any, Any] | None = None,
    ) -> None:
        """Append a completed conversation turn."""
        ...


class LegacyTranscriptStoreAdapter:
    """Lazily bridge transcript access to the historic singleton."""

    def __init__(self, factory: Callable[[], TranscriptStore]) -> None:
        self._factory = factory

    def append_turn(
        self,
        *,
        session_id: str,
        user: str,
        assistant: str,
        source: str = "agent",
        chat_id: str | None = None,
        metadata: dict[Any, Any] | None = None,
    ) -> None:
        """Resolve the store only when a projection is written."""
        self._factory().append_turn(
            session_id=session_id,
            user=user,
            assistant=assistant,
            source=source,
            chat_id=chat_id,
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """Dependencies shared by an application and its agents.

    The default instance deliberately bridges the historic singletons.  Callers can
    supply an isolated service set without changing existing construction paths.
    """

    tool_registry: ToolRegistry
    agent_registry: AgentRegistry
    skill_manager: SkillManager
    transcript_store: TranscriptStoreService
    memory_manager_factory: Callable[[Path | None], MemoryManager]

    @classmethod
    def default(cls) -> ApplicationServices:
        """Build services backed by the legacy process-wide registries."""
        return cls(
            tool_registry=get_tool_registry(),
            agent_registry=get_agent_registry(),
            skill_manager=get_skill_manager(),
            transcript_store=LegacyTranscriptStoreAdapter(get_transcript_store),
            memory_manager_factory=get_memory_manager,
        )

    def memory_manager(self, project_root: Path | None = None) -> MemoryManager:
        """Return the configured memory manager for a project root."""
        return self.memory_manager_factory(project_root)
