"""Tests for safe session persistence."""

import json
from unittest.mock import patch

import pytest

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
            "conversation_history": [],
            "tool": {
                "api_key": "secret",
                "headers": {"Authorization": "Bearer secret"},
            },
        }
    )

    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["session_id"] == "safe-session"
    assert data["tool"]["api_key"] == "[REDACTED]"
    assert data["tool"]["headers"]["Authorization"] == "[REDACTED]"
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_replace_failure_preserves_previous_session(tmp_path):
    store = SessionStore(tmp_path, "atomic")
    store.save({"value": "old"})

    with (
        patch("amcp.session_store.os.replace", side_effect=OSError("interrupted")),
        pytest.raises(SessionSaveError, match="interrupted"),
    ):
        store.save({"value": "new"})

    assert store.load()["value"] == "old"


def test_corrupt_session_has_explicit_diagnostic(tmp_path):
    store = SessionStore(tmp_path, "corrupt")
    store.path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(SessionLoadError, match="Could not load session corrupt"):
        store.load()
