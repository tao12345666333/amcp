"""
Memory system for AMCP.

Provides persistent cross-session memory for the agent using a two-layer approach:
- MEMORY.md: Long-term facts, preferences, and knowledge (curated, compact)
- HISTORY.md: Append-only searchable log of past activities and learnings

Memory is stored at:
- User-level: ~/.config/amcp/memory/
- Project-level: .amcp/memory/ (project-specific knowledge)

This enables the agent to remember important context across sessions,
supporting self-evolution by accumulating knowledge over time.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Default config directory
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "amcp"


@dataclass
class MemoryEntry:
    """A single entry in the history log."""

    timestamp: str
    session_id: str
    content: str
    tags: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Convert entry to markdown format for appending to HISTORY.md."""
        tags_str = f" [{', '.join(self.tags)}]" if self.tags else ""
        return f"### [{self.timestamp}] (session: {self.session_id}){tags_str}\n\n{self.content}\n"


@dataclass
class MemorySearchResult:
    """Result from searching memory."""

    line_number: int
    content: str
    source: str  # "memory" or "history"


class MemoryStore:
    """Two-layer memory system for persistent agent knowledge.

    Layer 1 - Long-term Memory (MEMORY.md):
        Curated facts, preferences, patterns, and key knowledge.
        The agent can read and rewrite this file to keep it organized.
        Should stay compact (<5000 words).

    Layer 2 - History Log (HISTORY.md):
        Append-only log of past activities, decisions, and learnings.
        Searchable via grep-style queries.
        Grows over time.
    """

    def __init__(self, memory_dir: Path):
        """Initialize memory store.

        Args:
            memory_dir: Directory to store memory files
        """
        self.memory_dir = memory_dir
        self.memory_file = memory_dir / "MEMORY.md"
        self.history_file = memory_dir / "HISTORY.md"

    @staticmethod
    def get_user_memory_dir() -> Path:
        """Get user-level memory directory."""
        return CONFIG_DIR / "memory"

    @staticmethod
    def get_project_memory_dir(project_root: Path | None = None) -> Path:
        """Get project-level memory directory."""
        root = project_root or Path.cwd()
        return root / ".amcp" / "memory"

    def _ensure_dir(self) -> None:
        """Ensure memory directory exists."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    # --- Long-term Memory (MEMORY.md) ---

    def read_long_term(self) -> str:
        """Read long-term memory content.

        Returns:
            Content of MEMORY.md, or empty string if not found
        """
        if self.memory_file.exists():
            try:
                return self.memory_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not read long-term memory: {e}")
        return ""

    def write_long_term(self, content: str) -> None:
        """Write (overwrite) long-term memory.

        The agent should curate this to keep it organized and compact.

        Args:
            content: New content for MEMORY.md
        """
        self._ensure_dir()
        try:
            self.memory_file.write_text(content, encoding="utf-8")
            logger.info(f"Updated long-term memory ({len(content)} chars)")
        except Exception as e:
            logger.error(f"Could not write long-term memory: {e}")

    # --- History Log (HISTORY.md) ---

    def append_history(
        self,
        content: str,
        session_id: str = "unknown",
        tags: list[str] | None = None,
    ) -> None:
        """Append an entry to the history log.

        Args:
            content: The content to log
            session_id: Current session ID
            tags: Optional tags for categorization
        """
        self._ensure_dir()
        entry = MemoryEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            session_id=session_id,
            content=content.strip(),
            tags=tags or [],
        )
        try:
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(entry.to_markdown() + "\n")
            logger.debug(f"Appended to history log: {content[:80]}...")
        except Exception as e:
            logger.error(f"Could not append to history: {e}")

    def read_history(self, max_lines: int = 500) -> str:
        """Read history log content.

        Args:
            max_lines: Maximum number of lines to return (from the end)

        Returns:
            Content of HISTORY.md (tail if too large), or empty string
        """
        if not self.history_file.exists():
            return ""
        try:
            content = self.history_file.read_text(encoding="utf-8")
            lines = content.split("\n")
            if len(lines) > max_lines:
                return "\n".join(lines[-max_lines:])
            return content
        except Exception as e:
            logger.warning(f"Could not read history: {e}")
            return ""

    def search_history(self, query: str, max_results: int = 20) -> list[MemorySearchResult]:
        """Search history log for matching entries.

        Args:
            query: Search query (case-insensitive substring match)
            max_results: Maximum results to return

        Returns:
            List of matching results with line numbers
        """
        results: list[MemorySearchResult] = []
        if not self.history_file.exists():
            return results

        try:
            pattern = re.compile(re.escape(query), re.IGNORECASE)
            lines = self.history_file.read_text(encoding="utf-8").split("\n")

            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    results.append(
                        MemorySearchResult(
                            line_number=i,
                            content=line.strip(),
                            source="history",
                        )
                    )
                    if len(results) >= max_results:
                        break
        except Exception as e:
            logger.warning(f"Could not search history: {e}")

        return results

    def search_memory(self, query: str, max_results: int = 20) -> list[MemorySearchResult]:
        """Search both long-term memory and history.

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            Combined results from both memory layers
        """
        results: list[MemorySearchResult] = []

        # Search long-term memory first
        if self.memory_file.exists():
            try:
                pattern = re.compile(re.escape(query), re.IGNORECASE)
                lines = self.memory_file.read_text(encoding="utf-8").split("\n")
                for i, line in enumerate(lines, 1):
                    if pattern.search(line):
                        results.append(
                            MemorySearchResult(
                                line_number=i,
                                content=line.strip(),
                                source="memory",
                            )
                        )
                        if len(results) >= max_results:
                            return results
            except Exception as e:
                logger.warning(f"Could not search memory: {e}")

        # Then search history
        remaining = max_results - len(results)
        if remaining > 0:
            results.extend(self.search_history(query, max_results=remaining))

        return results

    # --- Context Generation ---

    def get_memory_context(self) -> str:
        """Generate memory context for injection into agent prompts.

        Returns the long-term memory formatted for the system prompt.
        History is NOT included (too large); agent should use search tools.

        Returns:
            Formatted memory context string, or empty string
        """
        long_term = self.read_long_term()
        if not long_term:
            return ""

        return (
            "<memory>\n"
            "## Long-term Memory\n"
            "The following is your persistent memory from previous sessions. "
            "Use this context to provide continuity.\n\n"
            f"{long_term}\n"
            "</memory>"
        )

    def get_stats(self) -> dict[str, int | bool]:
        """Get memory statistics.

        Returns:
            Dictionary with memory stats
        """
        stats: dict[str, int | bool] = {
            "has_long_term": self.memory_file.exists(),
            "has_history": self.history_file.exists(),
            "long_term_size": 0,
            "history_size": 0,
            "history_entries": 0,
        }

        if self.memory_file.exists():
            stats["long_term_size"] = self.memory_file.stat().st_size

        if self.history_file.exists():
            stats["history_size"] = self.history_file.stat().st_size
            # Count entries by counting "### [" markers
            try:
                content = self.history_file.read_text(encoding="utf-8")
                stats["history_entries"] = content.count("### [")
            except Exception:
                pass

        return stats


class MemoryManager:
    """Manages both user-level and project-level memory stores.

    Provides a unified interface that merges context from both stores,
    with project-level memory taking precedence for search results.
    """

    def __init__(self, project_root: Path | None = None):
        """Initialize memory manager.

        Args:
            project_root: Project root directory (defaults to cwd)
        """
        self.user_store = MemoryStore(MemoryStore.get_user_memory_dir())
        self.project_store = MemoryStore(MemoryStore.get_project_memory_dir(project_root))

    def get_memory_context(self) -> str:
        """Get combined memory context from both stores.

        Returns:
            Combined memory context string
        """
        parts = []

        # User-level memory
        user_ctx = self.user_store.get_memory_context()
        if user_ctx:
            parts.append(user_ctx)

        # Project-level memory
        project_ctx = self.project_store.get_memory_context()
        if project_ctx:
            parts.append(project_ctx)

        return "\n\n".join(parts)

    def read_long_term(self, scope: str = "user") -> str:
        """Read long-term memory from the specified scope.

        Args:
            scope: "user" or "project"

        Returns:
            Memory content
        """
        store = self.project_store if scope == "project" else self.user_store
        return store.read_long_term()

    def write_long_term(self, content: str, scope: str = "user") -> None:
        """Write long-term memory to the specified scope.

        Args:
            content: Memory content
            scope: "user" or "project"
        """
        store = self.project_store if scope == "project" else self.user_store
        store.write_long_term(content)

    def append_history(
        self,
        content: str,
        session_id: str = "unknown",
        tags: list[str] | None = None,
        scope: str = "user",
    ) -> None:
        """Append to history log.

        Args:
            content: Content to log
            session_id: Session ID
            tags: Optional tags
            scope: "user" or "project"
        """
        store = self.project_store if scope == "project" else self.user_store
        store.append_history(content, session_id, tags)

    def search(self, query: str, max_results: int = 20) -> list[MemorySearchResult]:
        """Search across both memory stores.

        Args:
            query: Search query
            max_results: Maximum results

        Returns:
            Combined search results
        """
        results: list[MemorySearchResult] = []
        # Project results first (higher precedence)
        results.extend(self.project_store.search_memory(query, max_results))
        remaining = max_results - len(results)
        if remaining > 0:
            results.extend(self.user_store.search_memory(query, remaining))
        return results

    def get_stats(self) -> dict[str, dict[str, int | bool]]:
        """Get stats for both stores.

        Returns:
            Dictionary with user and project stats
        """
        return {
            "user": self.user_store.get_stats(),
            "project": self.project_store.get_stats(),
        }


# --- Global Memory Manager ---

_memory_manager: MemoryManager | None = None


def get_memory_manager(project_root: Path | None = None) -> MemoryManager:
    """Get or create the global memory manager.

    Args:
        project_root: Project root directory

    Returns:
        Global MemoryManager instance
    """
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager(project_root)
    return _memory_manager


def reset_memory_manager() -> None:
    """Reset the global memory manager (for testing)."""
    global _memory_manager
    _memory_manager = None
