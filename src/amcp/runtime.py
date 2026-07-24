"""Single-owner session runtime with per-turn results and cancellation."""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .message_queue import MessagePriority


class TurnStatus(StrEnum):
    """Lifecycle states for one submitted turn."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionRuntimeStatus(StrEnum):
    """Execution states owned by a session runtime."""

    IDLE = "idle"
    BUSY = "busy"
    CANCELLED = "cancelled"
    ERROR = "error"


class TurnCancelledError(asyncio.CancelledError):
    """Raised when awaiting a cancelled turn."""


@dataclass(frozen=True)
class TurnRequest:
    """Immutable request submitted to a session runtime."""

    id: str
    session_id: str
    prompt: str
    work_dir: Path | None
    stream: bool
    show_progress: bool
    priority: MessagePriority
    created_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class TurnResult:
    """Terminal result stored for every turn."""

    status: TurnStatus
    value: str | None = None
    error: BaseException | None = None


@dataclass(frozen=True)
class TurnEvent:
    """One observable turn state transition."""

    turn_id: str
    status: TurnStatus
    timestamp: datetime = field(default_factory=datetime.now)


class TurnHandle:
    """Track and await one turn independently from other queued turns."""

    def __init__(self, runtime: SessionRuntime, request: TurnRequest):
        self._runtime = runtime
        self.request = request
        self.status = TurnStatus.QUEUED
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self._completion: asyncio.Future[TurnResult] = asyncio.get_running_loop().create_future()
        self.events: asyncio.Queue[TurnEvent] = asyncio.Queue()
        self.events.put_nowait(TurnEvent(self.id, TurnStatus.QUEUED))

    @property
    def id(self) -> str:
        """Return the turn ID."""
        return self.request.id

    @property
    def done(self) -> bool:
        """Return whether the turn reached a terminal state."""
        return self._completion.done()

    @property
    def outcome(self) -> TurnResult | None:
        """Return the terminal outcome without blocking."""
        return self._completion.result() if self._completion.done() else None

    async def wait(self) -> str:
        """Wait for this turn and return its result or raise its terminal error."""
        result = await asyncio.shield(self._completion)
        if result.status == TurnStatus.CANCELLED:
            raise TurnCancelledError(f"Turn {self.id} was cancelled")
        if result.status == TurnStatus.FAILED:
            assert result.error is not None
            raise result.error
        return result.value or ""

    async def cancel(self) -> bool:
        """Cancel this queued or active turn."""
        return await self._runtime.cancel_turn(self.id)

    def _finish(self, result: TurnResult) -> None:
        if self.done:
            return
        self._transition(result.status)
        self.finished_at = datetime.now()
        self._completion.set_result(result)

    def _transition(self, status: TurnStatus) -> None:
        self.status = status
        self.events.put_nowait(TurnEvent(self.id, status))


RuntimeProcessor = Callable[[TurnRequest], Coroutine[Any, Any, str]]
RuntimeEventCallback = Callable[[str, TurnHandle], None]


class SessionRuntime:
    """Own a session queue, active task, turn states, and cancellation."""

    def __init__(
        self,
        session_id: str,
        processor: RuntimeProcessor,
        event_callback: RuntimeEventCallback | None = None,
    ):
        self.session_id = session_id
        self._processor = processor
        self._event_callback = event_callback
        self._queue: list[tuple[int, int, TurnHandle]] = []
        self._turns: dict[str, TurnHandle] = {}
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._worker: asyncio.Task[None] | None = None
        self._active_handle: TurnHandle | None = None
        self._active_task: asyncio.Task[str] | None = None
        self.status = SessionRuntimeStatus.IDLE

    @property
    def is_busy(self) -> bool:
        """Return whether a turn is active or queued."""
        return self._active_handle is not None or bool(self._queue)

    @property
    def queued_count(self) -> int:
        """Return the number of queued, not active, turns."""
        return len(self._queue)

    @property
    def active_turn(self) -> TurnHandle | None:
        """Return the currently running turn."""
        return self._active_handle

    def get_turn(self, turn_id: str) -> TurnHandle | None:
        """Return a previously submitted turn."""
        return self._turns.get(turn_id)

    def queued_prompts(self) -> list[str]:
        """Return queued prompts in execution order."""
        return [item[2].request.prompt for item in sorted(self._queue)]

    async def submit(
        self,
        prompt: str,
        *,
        work_dir: Path | None = None,
        stream: bool = True,
        show_progress: bool = True,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> TurnHandle:
        """Submit a turn and return its independent handle."""
        request = TurnRequest(
            id=f"turn-{uuid.uuid4().hex[:12]}",
            session_id=self.session_id,
            prompt=prompt,
            work_dir=work_dir.resolve() if work_dir else None,
            stream=stream,
            show_progress=show_progress,
            priority=priority,
        )
        handle = TurnHandle(self, request)
        async with self._lock:
            self._sequence += 1
            heapq.heappush(self._queue, (-priority.value, self._sequence, handle))
            self._turns[handle.id] = handle
            self._emit("turn.queued", handle)
            if self._worker is None or self._worker.done():
                self._worker = asyncio.create_task(
                    self._run_queue(),
                    name=f"amcp-session-{self.session_id}",
                )
        return handle

    async def cancel_active(self, *, clear_queue: bool = False) -> bool:
        """Cancel the active turn and optionally cancel all queued turns."""
        async with self._lock:
            task = self._active_task
            cancelled = task is not None and not task.done()
            if cancelled and task is not None:
                task.cancel()
            if clear_queue:
                self._cancel_queued_locked()
        if task is not None and cancelled:
            with contextlib.suppress(asyncio.CancelledError):
                await task
            if self._active_handle is not None and not self._active_handle.done:
                await asyncio.shield(self._active_handle._completion)
        return cancelled

    async def cancel_turn(self, turn_id: str) -> bool:
        """Cancel a queued or active turn by ID."""
        async with self._lock:
            handle = self._turns.get(turn_id)
            if handle is None or handle.done:
                return False
            if self._active_handle is handle:
                task = self._active_task
                if task is not None:
                    task.cancel()
            else:
                self._queue = [item for item in self._queue if item[2] is not handle]
                heapq.heapify(self._queue)
                handle._finish(TurnResult(TurnStatus.CANCELLED))
                self._emit("turn.cancelled", handle)
                return True
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task
            if not handle.done:
                await asyncio.shield(handle._completion)
        return True

    async def clear_queue(self) -> int:
        """Cancel all queued turns while preserving the active turn."""
        async with self._lock:
            return self._cancel_queued_locked()

    async def close(self) -> None:
        """Cancel all work and stop this runtime."""
        await self.cancel_active(clear_queue=True)
        worker = self._worker
        if worker is not None and not worker.done():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker

    def _cancel_queued_locked(self) -> int:
        count = len(self._queue)
        while self._queue:
            _, _, handle = heapq.heappop(self._queue)
            handle._finish(TurnResult(TurnStatus.CANCELLED))
            self._emit("turn.cancelled", handle)
        return count

    async def _run_queue(self) -> None:
        while True:
            async with self._lock:
                if not self._queue:
                    self._worker = None
                    if self.status not in {
                        SessionRuntimeStatus.CANCELLED,
                        SessionRuntimeStatus.ERROR,
                    }:
                        self.status = SessionRuntimeStatus.IDLE
                    return
                _, _, handle = heapq.heappop(self._queue)
                if handle.done:
                    continue
                self._active_handle = handle
                handle._transition(TurnStatus.RUNNING)
                handle.started_at = datetime.now()
                self.status = SessionRuntimeStatus.BUSY
                self._emit("turn.running", handle)
                task: asyncio.Task[str] = asyncio.create_task(
                    self._processor(handle.request),
                    name=f"amcp-turn-{handle.id}",
                )
                self._active_task = task

            try:
                value = await task
            except asyncio.CancelledError:
                handle._finish(TurnResult(TurnStatus.CANCELLED))
                self.status = SessionRuntimeStatus.CANCELLED
                self._emit("turn.cancelled", handle)
            except BaseException as exc:
                handle._finish(TurnResult(TurnStatus.FAILED, error=exc))
                self.status = SessionRuntimeStatus.ERROR
                self._emit("turn.failed", handle)
            else:
                handle._finish(TurnResult(TurnStatus.COMPLETED, value=value))
                self.status = SessionRuntimeStatus.IDLE
                self._emit("turn.completed", handle)
            finally:
                async with self._lock:
                    if self._active_handle is handle:
                        self._active_handle = None
                        self._active_task = None

    def _emit(self, event: str, handle: TurnHandle) -> None:
        if self._event_callback is not None:
            self._event_callback(event, handle)
