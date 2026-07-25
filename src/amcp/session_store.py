"""Safe JSON persistence for AMCP sessions."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from .session_state import InvalidSessionStateError, SessionState

SESSION_SCHEMA_VERSION = 2
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}


class SessionStoreError(Exception):
    """Base error for session persistence."""


class InvalidSessionIdError(SessionStoreError, ValueError):
    """Raised when a session ID is unsafe for use as a file name."""


class SessionLoadError(SessionStoreError):
    """Raised when persisted session data cannot be loaded safely."""


class SessionSaveError(SessionStoreError):
    """Raised when persisted session data cannot be saved atomically."""


def validate_session_id(session_id: str) -> str:
    """Validate and return a session ID safe for file-backed persistence."""
    if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.fullmatch(session_id) or ".." in session_id:
        raise InvalidSessionIdError("Session ID must be 1-128 safe filename characters and cannot contain '..'")
    return session_id


def redact_sensitive_data(value: Any) -> Any:
    """Return a JSON-compatible copy with common secret fields redacted."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in _SENSITIVE_KEYS else redact_sensitive_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    return value


class SessionStore:
    """Versioned JSON session store using atomic replacement."""

    def __init__(self, root: Path, session_id: str):
        self.root = root.expanduser()
        self.session_id = validate_session_id(session_id)
        self.path = self.root / f"{self.session_id}.json"
        self._lock = threading.RLock()

    def load(self) -> dict[str, Any] | None:
        """Load a session, returning ``None`` only when it does not exist."""
        with self._lock:
            if not self.path.exists():
                return None
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SessionLoadError(f"Could not load session {self.session_id}: {exc}") from exc

            if not isinstance(data, dict):
                raise SessionLoadError(f"Session {self.session_id} must contain a JSON object")
            version = data.get("schema_version")
            if version != SESSION_SCHEMA_VERSION or type(version) is not int:
                raise SessionLoadError(f"Unsupported session schema version {version!r} for {self.session_id}")
            try:
                state = SessionState.from_snapshot(data, self.session_id)
            except (InvalidSessionStateError, TypeError, ValueError) as exc:
                raise SessionLoadError(f"Invalid session state for {self.session_id}: {exc}") from exc
            return {
                **state.to_snapshot(),
                "schema_version": SESSION_SCHEMA_VERSION,
                "session_id": self.session_id,
            }

    def save(self, data: dict[str, Any]) -> None:
        """Atomically save a session without exposing partial JSON files."""
        payload = redact_sensitive_data(
            {
                **data,
                "schema_version": SESSION_SCHEMA_VERSION,
                "session_id": self.session_id,
            }
        )
        with self._lock:
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                fd, temp_name = tempfile.mkstemp(
                    dir=self.root,
                    prefix=f".{self.session_id}.",
                    suffix=".tmp",
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle, indent=2, ensure_ascii=False)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_name, self.path)
                except BaseException:
                    with suppress(OSError):
                        os.unlink(temp_name)
                    raise
            except (OSError, TypeError, ValueError) as exc:
                raise SessionSaveError(f"Could not save session {self.session_id}: {exc}") from exc

    def delete(self) -> None:
        """Delete the persisted session if present."""
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
            except OSError as exc:
                raise SessionStoreError(f"Could not delete session {self.session_id}: {exc}") from exc
