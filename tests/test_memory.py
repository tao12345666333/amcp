"""Tests for the memory system."""

from __future__ import annotations

from pathlib import Path

import pytest

from amcp.memory import MemoryManager, MemoryStore, reset_memory_manager
from amcp.tools import MemoryTool, ToolResult

# --- Fixtures ---


@pytest.fixture(autouse=True)
def _reset_manager():
    """Reset global memory manager before each test."""
    reset_memory_manager()
    yield
    reset_memory_manager()


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    """Create a temp memory directory."""
    d = tmp_path / "memory"
    d.mkdir()
    return d


@pytest.fixture
def store(memory_dir: Path) -> MemoryStore:
    return MemoryStore(memory_dir)


@pytest.fixture
def manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(project_root=tmp_path)


# --- Tests: MemoryStore ---


class TestMemoryStore:
    def test_read_empty_long_term(self, store: MemoryStore):
        """Reading non-existent long-term memory returns empty string."""
        assert store.read_long_term() == ""

    def test_write_and_read_long_term(self, store: MemoryStore):
        """Can write and read back long-term memory."""
        store.write_long_term("# Facts\n- Python 3.12\n- Uses async")
        content = store.read_long_term()
        assert "Python 3.12" in content
        assert "Uses async" in content

    def test_write_overwrites(self, store: MemoryStore):
        """Writing replaces all content."""
        store.write_long_term("Version 1")
        store.write_long_term("Version 2")
        assert store.read_long_term() == "Version 2"

    def test_append_history(self, store: MemoryStore):
        """Can append entries to history."""
        store.append_history("First entry", session_id="s1")
        store.append_history("Second entry", session_id="s2", tags=["test"])
        content = store.read_history()
        assert "First entry" in content
        assert "Second entry" in content
        assert "test" in content

    def test_history_append_only(self, store: MemoryStore):
        """History entries accumulate, not replace."""
        store.append_history("Entry 1", session_id="s1")
        store.append_history("Entry 2", session_id="s1")
        content = store.read_history()
        assert "Entry 1" in content
        assert "Entry 2" in content

    def test_read_history_with_limit(self, store: MemoryStore):
        """read_history respects max_lines."""
        for i in range(100):
            store.append_history(f"Entry {i}", session_id="s1")
        content = store.read_history(max_lines=10)
        lines = content.split("\n")
        assert len(lines) <= 10

    def test_search_history(self, store: MemoryStore):
        """Can search history for specific patterns."""
        store.append_history("Fixed auth bug", session_id="s1")
        store.append_history("Updated UI components", session_id="s1")
        store.append_history("Refactored auth module", session_id="s2")

        results = store.search_history("auth")
        assert len(results) == 2
        assert all(r.source == "history" for r in results)

    def test_search_history_case_insensitive(self, store: MemoryStore):
        """Search is case insensitive."""
        store.append_history("Fixed Python import", session_id="s1")
        results = store.search_history("python")
        assert len(results) >= 1

    def test_search_memory_both_layers(self, store: MemoryStore):
        """search_memory searches both long-term and history."""
        store.write_long_term("Project uses FastAPI framework")
        store.append_history("Deployed FastAPI service", session_id="s1")

        results = store.search_memory("FastAPI")
        assert len(results) == 2
        sources = {r.source for r in results}
        assert "memory" in sources
        assert "history" in sources

    def test_search_no_results(self, store: MemoryStore):
        """Search returns empty list for non-matching query."""
        store.write_long_term("Some content")
        results = store.search_memory("nonexistent-query-xyz")
        assert results == []

    def test_get_memory_context_empty(self, store: MemoryStore):
        """Context is empty when no memory exists."""
        assert store.get_memory_context() == ""

    def test_get_memory_context_formatted(self, store: MemoryStore):
        """Context includes formatted long-term memory."""
        store.write_long_term("# Key Facts\n- Uses Python 3.12")
        ctx = store.get_memory_context()
        assert "<memory>" in ctx
        assert "Long-term Memory" in ctx
        assert "Python 3.12" in ctx
        assert "</memory>" in ctx

    def test_get_stats(self, store: MemoryStore):
        """Stats reflect current state."""
        stats = store.get_stats()
        assert stats["has_long_term"] is False
        assert stats["has_history"] is False

        store.write_long_term("Some facts")
        store.append_history("An entry", session_id="s1")

        stats = store.get_stats()
        assert stats["has_long_term"] is True
        assert stats["has_history"] is True
        assert stats["long_term_size"] > 0
        assert stats["history_entries"] == 1

    def test_creates_directory_on_write(self, tmp_path: Path):
        """Writing to a non-existent directory creates it."""
        nested = tmp_path / "a" / "b" / "c"
        store = MemoryStore(nested)
        store.write_long_term("test")
        assert nested.exists()
        assert store.read_long_term() == "test"


# --- Tests: MemoryManager ---


class TestMemoryManager:
    def test_dual_scope(self, manager: MemoryManager):
        """Manager supports both user and project scopes."""
        manager.write_long_term("User knowledge", scope="user")
        manager.write_long_term("Project knowledge", scope="project")

        assert "User knowledge" in manager.read_long_term("user")
        assert "Project knowledge" in manager.read_long_term("project")

    def test_combined_context(self, manager: MemoryManager):
        """get_memory_context merges both scopes."""
        manager.write_long_term("Global prefs", scope="user")
        manager.write_long_term("Project config", scope="project")

        ctx = manager.get_memory_context()
        assert "Global prefs" in ctx
        assert "Project config" in ctx

    def test_cross_scope_search(self, manager: MemoryManager):
        """Search finds results across both scopes."""
        manager.write_long_term("Uses PostgreSQL database", scope="user")
        manager.write_long_term("PostgreSQL version 15", scope="project")

        results = manager.search("PostgreSQL")
        assert len(results) >= 2

    def test_append_history_scoped(self, manager: MemoryManager):
        """History entries go to the correct scope."""
        manager.append_history("User note", scope="user", session_id="s1")
        manager.append_history("Project note", scope="project", session_id="s1")

        user_results = manager.search("User note")
        project_results = manager.search("Project note")
        assert len(user_results) >= 1
        assert len(project_results) >= 1

    def test_stats_both_scopes(self, manager: MemoryManager):
        """Stats cover both scopes."""
        stats = manager.get_stats()
        assert "user" in stats
        assert "project" in stats


# --- Tests: MemoryTool ---


class TestMemoryTool:
    @pytest.fixture(autouse=True)
    def _setup_memory(self, tmp_path: Path, monkeypatch):
        """Set up memory in temp dir to avoid touching real files."""
        from amcp import memory

        # Create a manager with temp dirs
        user_dir = tmp_path / "user-memory"
        project_dir = tmp_path / "project"

        mgr = MemoryManager(project_root=project_dir)
        # Override user store to use temp dir
        mgr.user_store = MemoryStore(user_dir)

        monkeypatch.setattr(memory, "_memory_manager", mgr)
        self.tool = MemoryTool()

    def test_read_empty(self):
        """Read returns informative message for empty memory."""
        result = self.tool.execute(action="read")
        assert result.success
        assert "No long-term memory" in result.content

    def test_write_and_read(self):
        """Write then read returns the content."""
        self.tool.execute(action="write", content="# Notes\nImportant fact")
        result = self.tool.execute(action="read")
        assert result.success
        assert "Important fact" in result.content

    def test_append_and_search(self):
        """Append entries then search finds them."""
        self.tool.execute(action="append", content="Fixed login bug", tags=["bugfix"])
        result = self.tool.execute(action="search", query="login")
        assert result.success
        assert "login" in result.content.lower()

    def test_stats(self):
        """Stats action works."""
        result = self.tool.execute(action="stats")
        assert result.success
        assert "Memory Statistics" in result.content

    def test_write_requires_content(self):
        """Write without content fails."""
        result = self.tool.execute(action="write")
        assert not result.success
        assert "required" in result.error.lower()

    def test_search_requires_query(self):
        """Search without query fails."""
        result = self.tool.execute(action="search")
        assert not result.success
        assert "required" in result.error.lower()

    def test_invalid_action(self):
        """Invalid action returns error."""
        result = self.tool.execute(action="delete")
        assert not result.success
        assert "Invalid action" in result.error

    def test_scope_parameter(self):
        """Scope parameter directs to correct store."""
        self.tool.execute(action="write", content="User data", scope="user")
        self.tool.execute(action="write", content="Project data", scope="project")

        user_result = self.tool.execute(action="read", scope="user")
        project_result = self.tool.execute(action="read", scope="project")

        assert "User data" in user_result.content
        assert "Project data" in project_result.content
