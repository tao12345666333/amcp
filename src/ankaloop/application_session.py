"""Transport-neutral application service for session turn submission."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .runtime import (
    MessagePriority,
    TurnCancelledError,
    TurnEvent,
    TurnHandle,
    TurnStatus,
)

if TYPE_CHECKING:
    from .agent import Agent

TurnEventListener = Callable[[TurnEvent], None]


@dataclass(slots=True)
class SessionMetrics:
    """Application-level metrics derived from completed runtime turns."""

    status: str = "idle"
    message_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    updated_at: datetime | None = None


class ApplicationSessionService:
    """Submit turns and project runtime lifecycle into session metrics.

    CLI, embedded, server, Telegram, and delegated task entry points use this
    service so transport code does not own execution counters or status changes.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, SessionMetrics] = {}

    def metrics_for(self, agent: Agent) -> SessionMetrics:
        """Return the metrics projection for an agent session."""
        metrics = self._metrics.get(agent.session_id)
        if metrics is None:
            metrics = SessionMetrics(
                prompt_tokens=agent.total_input_tokens,
                completion_tokens=agent.total_output_tokens,
                total_tokens=agent.total_input_tokens + agent.total_output_tokens,
                updated_at=datetime.now(),
            )
            self._metrics[agent.session_id] = metrics
        return metrics

    def forget(self, session_id: str) -> None:
        """Drop application metrics after a session is permanently removed."""
        self._metrics.pop(session_id, None)

    async def submit(
        self,
        agent: Agent,
        content: str,
        *,
        work_dir: Path | None = None,
        stream: bool = True,
        show_progress: bool = False,
        priority: MessagePriority | str = MessagePriority.NORMAL,
        reject_if_busy: bool = False,
        on_event: TurnEventListener | None = None,
    ) -> TurnHandle:
        """Submit one turn through the agent's single runtime owner."""
        resolved_priority = self._resolve_priority(priority)
        handle = await agent.submit(
            content,
            work_dir=work_dir,
            stream=stream,
            show_progress=show_progress,
            priority=resolved_priority,
            reject_if_busy=reject_if_busy,
        )
        metrics = self.metrics_for(agent)
        metrics.status = "busy"
        metrics.updated_at = datetime.now()
        handle.add_done_callback(lambda completed: self._project_completion(agent, completed))
        if on_event is not None:
            with contextlib.suppress(Exception):
                on_event(TurnEvent.transition(handle.id, TurnStatus.QUEUED))
            handle.add_event_callback(on_event)
        return handle

    async def run(
        self,
        agent: Agent,
        content: str,
        *,
        work_dir: Path | None = None,
        stream: bool = True,
        show_progress: bool = False,
        priority: MessagePriority | str = MessagePriority.NORMAL,
        reject_if_busy: bool = False,
        on_event: TurnEventListener | None = None,
    ) -> str:
        """Submit and await one turn while preserving cancellation ownership."""
        handle = await self.submit(
            agent,
            content,
            work_dir=work_dir,
            stream=stream,
            show_progress=show_progress,
            priority=priority,
            reject_if_busy=reject_if_busy,
            on_event=on_event,
        )
        try:
            return await handle.wait()
        except TurnCancelledError:
            raise
        except asyncio.CancelledError as cancelled:
            cancel_task = asyncio.create_task(handle.cancel())
            while not cancel_task.done():
                try:
                    await asyncio.shield(cancel_task)
                except asyncio.CancelledError:
                    continue
            if not cancel_task.cancelled():
                with contextlib.suppress(Exception):
                    cancel_task.result()
            raise cancelled

    def _project_completion(self, agent: Agent, handle: TurnHandle) -> None:
        """Update counters exactly once when a turn reaches a terminal state."""
        metrics = self.metrics_for(agent)
        has_pending_work = agent.has_pending_work(excluding=handle)
        if handle.status == TurnStatus.COMPLETED:
            metrics.message_count += 1
            metrics.status = "busy" if has_pending_work else "idle"
        elif handle.status == TurnStatus.CANCELLED:
            metrics.status = "busy" if has_pending_work else "cancelled"
        else:
            metrics.status = "busy" if has_pending_work else "error"
        metrics.prompt_tokens = agent.total_input_tokens
        metrics.completion_tokens = agent.total_output_tokens
        metrics.total_tokens = metrics.prompt_tokens + metrics.completion_tokens
        metrics.updated_at = datetime.now()

    @staticmethod
    def _resolve_priority(priority: MessagePriority | str) -> MessagePriority:
        """Normalize public priority strings into the runtime enum."""
        if isinstance(priority, MessagePriority):
            return priority
        priorities = {
            "low": MessagePriority.LOW,
            "normal": MessagePriority.NORMAL,
            "high": MessagePriority.HIGH,
            "urgent": MessagePriority.URGENT,
        }
        return priorities.get(str(priority).lower(), MessagePriority.NORMAL)
