"""Tests for safe session persistence."""

import json
from dataclasses import asdict
from unittest.mock import patch

import pytest

from amcp.session_state import CanonicalTurn, CompactionCheckpoint, SessionState
from amcp.session_store import (
    InvalidSessionIdError,
    SessionConflictError,
    SessionLoadError,
    SessionSaveError,
    SessionStore,
    SessionTimelineStore,
)


@pytest.mark.parametrize("session_id", ["../escape", "a/b", "", "..", "x" * 129])
def test_rejects_unsafe_session_ids(tmp_path, session_id):
    with pytest.raises(InvalidSessionIdError):
        SessionStore(tmp_path, session_id)


def test_save_is_versioned_atomic_and_redacts_sensitive_fields(tmp_path):
    store = SessionStore(tmp_path, "safe-session")
    store.save(
        {
            "conversation": {"messages": [], "turns": []},
            "compaction_checkpoint": None,
            "usage": {},
            "diagnostics": {},
            "tool": {
                "api_key": "secret",
                "headers": {"Authorization": "Bearer secret"},
            },
        }
    )

    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["session_id"] == "safe-session"
    assert data["tool"]["api_key"] == "[REDACTED]"
    assert data["tool"]["headers"]["Authorization"] == "[REDACTED]"
    assert not list(tmp_path.glob("*.tmp"))


def test_timeline_is_sanitized_bounded_and_restartable(tmp_path):
    store = SessionTimelineStore(tmp_path, "timeline", max_events=3)
    store.append(
        "tool.call_start",
        {
            "tool_name": "bash",
            "tool_id": "call-1",
            "arguments": {"command": "echo secret"},
            "error": "Bearer secret",
        },
    )
    store.append("tool.call_complete", {"tool_name": "bash", "success": True})
    store.append("llm.usage", {"input_tokens": 10, "output_tokens": 2})
    store.append("turn.completed", {"turn_id": "turn-1", "turn_status": "completed"})

    restarted = SessionTimelineStore(tmp_path, "timeline", max_events=3)
    events = restarted.read(limit=10)

    assert [event["type"] for event in events] == ["llm.usage", "turn.completed"]
    assert events[0]["data"] == {"input_tokens": 10, "output_tokens": 2}
    raw = restarted.path.read_text(encoding="utf-8")
    assert "echo secret" not in raw
    assert "Bearer secret" not in raw


def test_timeline_retention_is_shared_across_writers(tmp_path):
    first = SessionTimelineStore(tmp_path, "shared-timeline", max_events=3)
    second = SessionTimelineStore(tmp_path, "shared-timeline", max_events=3)

    for index in range(8):
        writer = first if index % 2 == 0 else second
        writer.append("turn.completed", {"turn_id": f"turn-{index}"})

    events = first.read(limit=10)
    assert len(events) <= 3
    assert events[-1]["data"]["turn_id"] == "turn-7"


def test_atomic_replace_failure_preserves_previous_session(tmp_path):
    store = SessionStore(tmp_path, "atomic")
    old = SessionState(session_id="atomic", agent_name="test").to_snapshot()
    store.save(old)

    with (
        patch("amcp.session_store.os.replace", side_effect=OSError("interrupted")),
        pytest.raises(SessionSaveError, match="interrupted"),
    ):
        store.save(SessionState(session_id="atomic", agent_name="new").to_snapshot())

    assert store.load()["agent_name"] == "test"


def test_stale_session_owner_cannot_overwrite_newer_revision(tmp_path):
    initial_store = SessionStore(tmp_path, "shared")
    initial_store.save(SessionState(session_id="shared", agent_name="test").to_snapshot())

    first_store = SessionStore(tmp_path, "shared")
    second_store = SessionStore(tmp_path, "shared")
    first = SessionState.from_snapshot(first_store.load(), "shared")
    second = SessionState.from_snapshot(second_store.load(), "shared")

    first.commit_turn(
        "first",
        [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "saved"},
        ],
    )
    first.revision = first_store.save(
        first.to_snapshot(),
        expected_revision=first.revision,
    )

    second.commit_turn(
        "second",
        [
            {"role": "user", "content": "two"},
            {"role": "assistant", "content": "stale"},
        ],
    )
    with pytest.raises(SessionConflictError, match="changed from revision"):
        second_store.save(second.to_snapshot(), expected_revision=second.revision)

    persisted = SessionState.from_snapshot(first_store.load(), "shared")
    assert persisted.revision == first.revision
    assert [turn.turn_id for turn in persisted.turns] == ["first"]


def test_corrupt_session_has_explicit_diagnostic(tmp_path):
    store = SessionStore(tmp_path, "corrupt")
    store.path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(SessionLoadError, match="Could not load session corrupt"):
        store.load()


@pytest.mark.parametrize("schema_version", [None, 0, 1, 3, True])
def test_rejects_any_schema_other_than_v2(tmp_path, schema_version):
    store = SessionStore(tmp_path, "unsupported")
    payload = {"conversation_history": []}
    if schema_version is not None:
        payload["schema_version"] = schema_version
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SessionLoadError, match="Unsupported session schema version"):
        store.load()


def test_rejects_broken_tool_batch(tmp_path):
    store = SessionStore(tmp_path, "broken")
    state = SessionState(
        session_id="broken",
        agent_name="default",
        messages=[
            {"role": "user", "content": "inspect"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {"role": "assistant", "content": "done"},
        ],
        turns=[
            CanonicalTurn(
                turn_id="turn-1",
                start_message=0,
                end_message=3,
                completed_at="2026-01-01T00:00:00",
            )
        ],
    )
    raw = {
        "schema_version": 2,
        "session_id": "broken",
        "agent_name": "default",
        "conversation": {
            "messages": state.messages,
            "turns": [asdict(state.turns[0])],
        },
        "compaction_checkpoint": None,
        "usage": {},
        "diagnostics": {},
    }
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SessionLoadError, match="Every tool call"):
        store.load()


def test_rejects_checkpoint_inside_a_turn(tmp_path):
    store = SessionStore(tmp_path, "checkpoint")
    state = SessionState(session_id="checkpoint", agent_name="default")
    state.commit_turn(
        "turn-1",
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    state.checkpoint = CompactionCheckpoint(
        context=[{"role": "assistant", "content": "summary"}],
        covered_message_count=1,
        covered_turn_count=1,
        generation=1,
        strategy="summary",
        strategy_version=1,
        original_tokens=10,
        compacted_tokens=2,
    )
    raw = {
        "schema_version": 2,
        "session_id": "checkpoint",
        "agent_name": "default",
        "conversation": {
            "messages": state.messages,
            "turns": [asdict(state.turns[0])],
        },
        "compaction_checkpoint": asdict(state.checkpoint),
        "usage": {},
        "diagnostics": {},
    }
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SessionLoadError, match="complete turn boundary"):
        store.load()


def test_rejects_checkpoint_with_invalid_field_types(tmp_path):
    store = SessionStore(tmp_path, "checkpoint-types")
    state = SessionState(session_id="checkpoint-types", agent_name="default")
    state.commit_turn(
        "turn-1",
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    raw = {
        "schema_version": 2,
        "session_id": "checkpoint-types",
        "agent_name": "default",
        "conversation": {
            "messages": state.messages,
            "turns": [asdict(state.turns[0])],
        },
        "compaction_checkpoint": {
            "context": [{"role": "assistant", "content": "summary"}],
            "covered_message_count": 2,
            "covered_turn_count": "1",
            "generation": 1,
            "strategy": "summary",
            "strategy_version": 1,
            "original_tokens": 10,
            "compacted_tokens": 2,
        },
        "usage": {},
        "diagnostics": {},
    }
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SessionLoadError, match="checkpoint fields have invalid types"):
        store.load()
