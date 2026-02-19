"""Tests for the SQLite+FTS5 memory system."""

from __future__ import annotations

from pathlib import Path

import pytest

from amcp.memory import MemoryManager, MemoryStore, reset_memory_manager
from amcp.memory_store import SQLiteMemoryStore
from amcp.tools import MemoryTool

# --- Fixtures ---


@pytest.fixture(autouse=True)
def _reset_manager():
    """Reset global memory manager before each test."""
    reset_memory_manager()
    yield
    reset_memory_manager()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "memory" / "memory.db"


@pytest.fixture
def sqlite_store(db_path: Path) -> SQLiteMemoryStore:
    store = SQLiteMemoryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    d = tmp_path / "memory"
    d.mkdir()
    return d


@pytest.fixture
def store(memory_dir: Path) -> MemoryStore:
    return MemoryStore(memory_dir)


# --- Tests: SQLiteMemoryStore ---


class TestSQLiteMemoryStore:
    def test_creates_db_and_directory(self, db_path: Path):
        """DB file and parent directory are created on first access."""
        store = SQLiteMemoryStore(db_path)
        store.append_event("test event")
        assert db_path.exists()
        store.close()

    def test_append_and_search_events(
        self, sqlite_store: SQLiteMemoryStore
    ):
        """Can append events and search them via FTS5."""
        sqlite_store.append_event(
            "Fixed authentication bug in login module",
            session_id="s1",
            tags=["bugfix", "auth"],
        )
        sqlite_store.append_event(
            "Updated user interface components",
            session_id="s1",
            tags=["ui"],
        )
        sqlite_store.append_event(
            "Refactored authentication middleware",
            session_id="s2",
            tags=["refactor", "auth"],
        )

        results = sqlite_store.search_events("authentication")
        assert len(results) == 2
        assert all(r.source == "events" for r in results)

    def test_search_events_no_results(
        self, sqlite_store: SQLiteMemoryStore
    ):
        """Search returns empty list for non-matching query."""
        sqlite_store.append_event("some content")
        results = sqlite_store.search_events("nonexistent_xyz_query")
        assert results == []

    def test_get_recent_events(self, sqlite_store: SQLiteMemoryStore):
        """Can retrieve recent events in reverse chronological order."""
        for i in range(5):
            sqlite_store.append_event(f"Event {i}", session_id=f"s{i}")
        recent = sqlite_store.get_recent_events(limit=3)
        assert len(recent) == 3
        assert recent[0]["content"] == "Event 4"

    def test_upsert_and_get_fact(self, sqlite_store: SQLiteMemoryStore):
        """Can upsert and retrieve a fact."""
        sqlite_store.upsert_fact(
            key="python_version",
            value="3.12",
            category="config",
        )
        fact = sqlite_store.get_fact("python_version")
        assert fact is not None
        assert fact["value"] == "3.12"
        assert fact["category"] == "config"

    def test_upsert_updates_existing(
        self, sqlite_store: SQLiteMemoryStore
    ):
        """Upserting with same key updates the value."""
        sqlite_store.upsert_fact(key="lang", value="Python 3.11")
        sqlite_store.upsert_fact(key="lang", value="Python 3.12")
        fact = sqlite_store.get_fact("lang")
        assert fact["value"] == "Python 3.12"

    def test_get_fact_not_found(self, sqlite_store: SQLiteMemoryStore):
        """get_fact returns None for missing key."""
        assert sqlite_store.get_fact("nonexistent") is None

    def test_search_facts(self, sqlite_store: SQLiteMemoryStore):
        """Can search facts via FTS5."""
        sqlite_store.upsert_fact("db_type", "PostgreSQL 15", "infra")
        sqlite_store.upsert_fact("cache_type", "Redis 7", "infra")
        sqlite_store.upsert_fact("lang", "Python 3.12", "config")

        results = sqlite_store.search_facts("PostgreSQL")
        assert len(results) == 1
        assert results[0]["key"] == "db_type"

    def test_list_facts_all(self, sqlite_store: SQLiteMemoryStore):
        """list_facts returns all facts when no category filter."""
        sqlite_store.upsert_fact("k1", "v1", "cat1")
        sqlite_store.upsert_fact("k2", "v2", "cat2")
        facts = sqlite_store.list_facts()
        assert len(facts) == 2

    def test_list_facts_by_category(
        self, sqlite_store: SQLiteMemoryStore
    ):
        """list_facts filters by category."""
        sqlite_store.upsert_fact("k1", "v1", "cat1")
        sqlite_store.upsert_fact("k2", "v2", "cat2")
        sqlite_store.upsert_fact("k3", "v3", "cat1")
        facts = sqlite_store.list_facts(category="cat1")
        assert len(facts) == 2
        assert all(f["category"] == "cat1" for f in facts)

    def test_delete_fact(self, sqlite_store: SQLiteMemoryStore):
        """Can delete a fact by key."""
        sqlite_store.upsert_fact("temp", "value")
        assert sqlite_store.delete_fact("temp") is True
        assert sqlite_store.get_fact("temp") is None

    def test_delete_fact_not_found(
        self, sqlite_store: SQLiteMemoryStore
    ):
        """Deleting non-existent fact returns False."""
        assert sqlite_store.delete_fact("nonexistent") is False

    def test_combined_search(self, sqlite_store: SQLiteMemoryStore):
        """Combined search returns facts first, then events."""
        sqlite_store.upsert_fact(
            "framework", "FastAPI web framework", "config"
        )
        sqlite_store.append_event("Deployed FastAPI service")

        results = sqlite_store.search("FastAPI")
        assert len(results) == 2
        # Facts come first
        assert results[0].source == "facts"
        assert results[1].source == "events"

    def test_stats(self, sqlite_store: SQLiteMemoryStore):
        """Stats reflect current counts."""
        stats = sqlite_store.get_stats()
        assert stats["event_count"] == 0
        assert stats["fact_count"] == 0

        sqlite_store.append_event("event 1")
        sqlite_store.upsert_fact("k1", "v1")

        stats = sqlite_store.get_stats()
        assert stats["event_count"] == 1
        assert stats["fact_count"] == 1
        assert stats["db_size_bytes"] > 0

    def test_empty_query_returns_empty(
        self, sqlite_store: SQLiteMemoryStore
    ):
        """Empty search query returns empty results."""
        sqlite_store.append_event("some content")
        assert sqlite_store.search_events("") == []
        assert sqlite_store.search_facts("") == []
        assert sqlite_store.search("") == []

    def test_special_characters_in_query(
        self, sqlite_store: SQLiteMemoryStore
    ):
        """Special FTS5 characters are safely handled."""
        sqlite_store.append_event("error in module: auth.py")
        # These should not crash
        sqlite_store.search_events("auth.py")
        sqlite_store.search_events("OR AND NOT")
        sqlite_store.search_events('"quoted"')


# --- Tests: MemoryStore integration with SQLite ---


class TestMemoryStoreIntegration:
    def test_append_history_writes_to_sqlite(self, store: MemoryStore):
        """append_history writes to both markdown and SQLite."""
        store.append_history(
            "Test entry", session_id="s1", tags=["test"]
        )
        # Check markdown file
        content = store.read_history()
        assert "Test entry" in content

        # Check SQLite events
        events = store._sqlite.get_recent_events(limit=1)
        assert len(events) == 1
        assert events[0]["content"] == "Test entry"

    def test_search_history_uses_sqlite(self, store: MemoryStore):
        """search_history prefers SQLite FTS5 results."""
        store.append_history("Fixed login authentication bug")
        store.append_history("Updated dashboard layout")

        results = store.search_history("authentication")
        assert len(results) >= 1
        assert any("authentication" in r.content for r in results)

    def test_search_memory_includes_facts(self, store: MemoryStore):
        """search_memory includes SQLite facts."""
        store.upsert_fact("db_engine", "PostgreSQL database", "infra")
        results = store.search_memory("PostgreSQL")
        assert len(results) >= 1
        assert any(r.source == "facts" for r in results)

    def test_fact_operations_on_store(self, store: MemoryStore):
        """Fact CRUD operations work through MemoryStore."""
        store.upsert_fact("key1", "value1", "cat1")
        assert store.get_fact("key1")["value"] == "value1"

        facts = store.list_facts(category="cat1")
        assert len(facts) == 1

        store.search_facts("value1")

        assert store.delete_fact("key1") is True
        assert store.get_fact("key1") is None

    def test_stats_include_sqlite(self, store: MemoryStore):
        """Stats include SQLite metrics."""
        store.append_history("event", session_id="s1")
        store.upsert_fact("k", "v")

        stats = store.get_stats()
        assert stats["sqlite_event_count"] == 1
        assert stats["sqlite_fact_count"] == 1


# --- Tests: MemoryTool new actions ---


class TestMemoryToolFacts:
    @pytest.fixture(autouse=True)
    def _setup_memory(self, tmp_path: Path, monkeypatch):
        """Set up memory in temp dir."""
        from amcp import memory

        user_dir = tmp_path / "user-memory"
        project_dir = tmp_path / "project"
        mgr = MemoryManager(project_root=project_dir)
        mgr.user_store = MemoryStore(user_dir)
        monkeypatch.setattr(memory, "_memory_manager", mgr)
        self.tool = MemoryTool()

    def test_upsert_fact(self):
        """upsert_fact action saves a fact."""
        result = self.tool.execute(
            action="upsert_fact",
            key="python_version",
            content="3.12",
            category="config",
        )
        assert result.success
        assert "saved" in result.content

    def test_upsert_fact_requires_key(self):
        """upsert_fact requires key parameter."""
        result = self.tool.execute(
            action="upsert_fact", content="value"
        )
        assert not result.success
        assert "Key is required" in result.error

    def test_upsert_fact_requires_content(self):
        """upsert_fact requires content parameter."""
        result = self.tool.execute(
            action="upsert_fact", key="mykey"
        )
        assert not result.success
        assert "Content is required" in result.error

    def test_get_fact(self):
        """get_fact retrieves a saved fact."""
        self.tool.execute(
            action="upsert_fact",
            key="lang",
            content="Python",
            category="config",
        )
        result = self.tool.execute(action="get_fact", key="lang")
        assert result.success
        assert "Python" in result.content
        assert "config" in result.content

    def test_get_fact_not_found(self):
        """get_fact returns info message when not found."""
        result = self.tool.execute(action="get_fact", key="missing")
        assert result.success
        assert "No fact found" in result.content

    def test_get_fact_requires_key(self):
        """get_fact requires key parameter."""
        result = self.tool.execute(action="get_fact")
        assert not result.success
        assert "Key is required" in result.error

    def test_list_facts(self):
        """list_facts returns saved facts."""
        self.tool.execute(
            action="upsert_fact",
            key="k1",
            content="v1",
            category="cat1",
        )
        self.tool.execute(
            action="upsert_fact",
            key="k2",
            content="v2",
            category="cat1",
        )
        result = self.tool.execute(
            action="list_facts", category="cat1"
        )
        assert result.success
        assert "2 facts" in result.content

    def test_list_facts_empty(self):
        """list_facts returns message when no facts."""
        result = self.tool.execute(action="list_facts")
        assert result.success
        assert "No facts found" in result.content

    def test_delete_fact(self):
        """delete_fact removes a fact."""
        self.tool.execute(
            action="upsert_fact", key="temp", content="data"
        )
        result = self.tool.execute(action="delete_fact", key="temp")
        assert result.success
        assert "deleted" in result.content

        result = self.tool.execute(action="get_fact", key="temp")
        assert "No fact found" in result.content

    def test_delete_fact_not_found(self):
        """delete_fact returns message for missing key."""
        result = self.tool.execute(
            action="delete_fact", key="missing"
        )
        assert result.success
        assert "No fact found" in result.content

    def test_delete_fact_requires_key(self):
        """delete_fact requires key parameter."""
        result = self.tool.execute(action="delete_fact")
        assert not result.success
        assert "Key is required" in result.error

    def test_invalid_action_includes_new_actions(self):
        """Invalid action error lists all available actions."""
        result = self.tool.execute(action="bogus")
        assert not result.success
        assert "upsert_fact" in result.error
        assert "delete_fact" in result.error

    def test_scope_parameter_for_facts(self):
        """Facts respect scope parameter."""
        self.tool.execute(
            action="upsert_fact",
            key="proj_key",
            content="proj_val",
            scope="project",
        )
        # Should not be in user scope
        result = self.tool.execute(
            action="get_fact", key="proj_key", scope="user"
        )
        assert "No fact found" in result.content

        # Should be in project scope
        result = self.tool.execute(
            action="get_fact", key="proj_key", scope="project"
        )
        assert "proj_val" in result.content
