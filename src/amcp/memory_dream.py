"""Background memory consolidation for long-running AMCP sessions."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_config
from .llm import create_llm_client
from .memory import MemoryStore, get_memory_manager

logger = logging.getLogger(__name__)

DREAM_MIN_INTERVAL_SECONDS = 4 * 60 * 60
DREAM_MIN_NEW_EVENTS = 10
DREAM_MAX_EVENTS = 80
DREAM_LOCK_STALE_SECONDS = 60 * 60

DREAM_PROMPT = """\
You are consolidating AMCP memory for a long-running Telegram assistant.

Update the existing project MEMORY.md using the recent session events below.

Keep:
- Durable user preferences and expectations.
- Stable project facts, decisions, constraints, and rationale.
- Repeated plans, ongoing goals, blockers, and follow-ups that are still useful.

Discard:
- Greetings, transient task chatter, duplicate status updates, and raw tool noise.
- Completed-work logs that are only useful as transcript history.
- Relative dates unless you rewrite them as absolute dates from the event timestamps.

Return the complete updated MEMORY.md as concise Markdown with headings.
If nothing durable should be changed, reply exactly: NO_REPLY.
"""


@dataclass
class DreamRunResult:
    """Result of one memory dream pass."""

    ran: bool
    updated: bool
    reason: str


class MemoryDreamer:
    """Consolidate recent episodic memory into project long-term memory."""

    def __init__(
        self,
        project_root: Path,
        *,
        min_interval_seconds: int = DREAM_MIN_INTERVAL_SECONDS,
        min_new_events: int = DREAM_MIN_NEW_EVENTS,
        client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self.project_root = project_root
        self.min_interval_seconds = min_interval_seconds
        self.min_new_events = min_new_events
        self._client = client
        self._model = model
        self.memory_dir = MemoryStore.get_project_memory_dir(project_root)
        self.state_file = self.memory_dir / "dream_state.json"
        self.lock_file = self.memory_dir / "dream.lock"

    def run_once(self) -> DreamRunResult:
        """Run one gated consolidation pass."""
        state = self._load_state()
        events = self._recent_events()
        if not events:
            return DreamRunResult(ran=False, updated=False, reason="no_events")

        latest_event_id = max(int(event.get("id", 0)) for event in events)
        last_event_id = int(state.get("last_event_id", 0))
        new_events = [event for event in events if int(event.get("id", 0)) > last_event_id]
        if len(new_events) < self.min_new_events:
            return DreamRunResult(ran=False, updated=False, reason="not_enough_new_events")

        last_run_at = float(state.get("last_run_at", 0))
        if time.time() - last_run_at < self.min_interval_seconds:
            return DreamRunResult(ran=False, updated=False, reason="too_soon")

        if not self._acquire_lock():
            return DreamRunResult(ran=False, updated=False, reason="locked")

        try:
            updated_memory = self._consolidate(events)
            self._save_state({"last_run_at": time.time(), "last_event_id": latest_event_id})
            if not updated_memory:
                return DreamRunResult(ran=True, updated=False, reason="no_reply")

            manager = get_memory_manager(self.project_root)
            manager.write_long_term(updated_memory, scope="project")
            return DreamRunResult(ran=True, updated=True, reason="updated")
        except Exception as e:
            logger.debug(f"Memory dream failed (non-critical): {e}")
            return DreamRunResult(ran=True, updated=False, reason="error")
        finally:
            self._release_lock()

    def _recent_events(self) -> list[dict[str, Any]]:
        manager = get_memory_manager(self.project_root)
        try:
            return manager.project_store._sqlite.get_recent_events(limit=DREAM_MAX_EVENTS)
        except Exception as e:
            logger.debug(f"Could not load dream events: {e}")
            return []

    def _consolidate(self, events: list[dict[str, Any]]) -> str:
        manager = get_memory_manager(self.project_root)
        existing = manager.read_long_term(scope="project").strip()
        event_text = self._format_events(events)
        client = self._client or self._make_client()
        model = self._model or self._resolve_model()
        response = client.chat(
            messages=[
                {"role": "system", "content": DREAM_PROMPT},
                {
                    "role": "user",
                    "content": f"Existing MEMORY.md:\n\n{existing or '(empty)'}\n\nRecent events:\n\n{event_text}",
                },
            ],
            model=model,
        )
        content = (response.content or "").strip()
        if not content or content == "NO_REPLY":
            return ""
        if "#" not in content:
            logger.debug("Memory dream rejected non-Markdown response")
            return ""
        return content

    @staticmethod
    def _format_events(events: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for event in reversed(events):
            content = str(event.get("content", "")).strip()
            if not content:
                continue
            lines.append(f"- [{event.get('timestamp', '')} session:{event.get('session_id', 'unknown')}] {content}")
        return "\n".join(lines)

    def _make_client(self) -> Any:
        cfg = load_config()
        return create_llm_client(cfg.chat)

    def _resolve_model(self) -> str:
        cfg = load_config()
        if cfg.chat and cfg.chat.model:
            return cfg.chat.model
        return "DeepSeek-V3.1-Terminus"

    def _load_state(self) -> dict[str, Any]:
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.debug(f"Could not read memory dream state: {e}")
        return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _acquire_lock(self) -> bool:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock_file.open("x", encoding="utf-8") as f:
                f.write(str(time.time()))
            return True
        except FileExistsError:
            try:
                age = time.time() - float(self.lock_file.read_text(encoding="utf-8") or "0")
            except (OSError, ValueError):
                age = 0
            if age < DREAM_LOCK_STALE_SECONDS:
                return False
            try:
                self.lock_file.unlink()
            except OSError:
                return False
            return self._acquire_lock()

    def _release_lock(self) -> None:
        try:
            self.lock_file.unlink()
        except FileNotFoundError:
            return
        except OSError as e:
            logger.debug(f"Could not release memory dream lock: {e}")
