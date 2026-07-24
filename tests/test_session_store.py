"""Tests for safe session persistence."""

import json
from dataclasses import asdict
from unittest.mock import patch

import pytest

from amcp.session_state import CanonicalTurn, CompactionCheckpoint, SessionState
from amcp.session_store import (
    InvalidSessionIdError,
    SessionLoadError,
    SessionSaveError,
    SessionStore,
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


def test_corrupt_session_has_explicit_diagnostic(tmp_path):
    store = SessionStore(tmp_path, "corrupt")
    store.path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(SessionLoadError, match="Could not load session corrupt"):
        store.load()


def test_migrates_v1_history_without_inventing_tool_messages(tmp_path):
    store = SessionStore(tmp_path, "legacy")
    store.path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": "legacy",
                "agent_name": "default",
                "conversation_history": [
                    {"role": "user", "content": "inspect"},
                    {"role": "assistant", "content": "done"},
                ],
                "tool_calls_history": [{"tool": "read_file"}],
            }
        ),
        encoding="utf-8",
    )

    data = store.load()

    assert data["schema_version"] == 2
    assert [message["role"] for message in data["conversation"]["messages"]] == [
        "user",
        "assistant",
    ]
    assert data["conversation"]["turns"][0]["legacy"] is True
    assert all(message["role"] != "tool" for message in data["conversation"]["messages"])


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
