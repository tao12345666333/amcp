"""TaskRunner — managed agent execution pool for the AMCP daemon."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result of a completed task."""

    task_id: str
    command: str
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float = 0.0


class TaskRunner:
    """Manage a pool of concurrent agent tasks.

    The runner enforces a concurrency limit and keeps a history of
    completed tasks for audit purposes.
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        *,
        agent_factory: Callable[..., Any] | None = None,
    ):
        self.max_concurrent = max_concurrent
        self._agent_factory = agent_factory
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active: dict[str, asyncio.Task] = {}
        self._history: list[TaskResult] = []
        self._counter = 0

    # ------------------------------------------------------------------
    # Submit tasks
    # ------------------------------------------------------------------

    async def submit(
        self,
        command: str,
        *,
        skill: str | None = None,
        work_dir: str | None = None,
        timeout: int = 300,
    ) -> str:
        """Submit a new task and return its ID."""
        self._counter += 1
        task_id = f"task-{self._counter:04d}"
        task = asyncio.create_task(self._run(task_id, command, skill, work_dir, timeout))
        self._active[task_id] = task
        task.add_done_callback(lambda _t: self._active.pop(task_id, None))
        logger.info("Submitted task %s: %s", task_id, command[:80])
        return task_id

    async def _run(
        self,
        task_id: str,
        command: str,
        skill: str | None,
        work_dir: str | None,
        timeout: int,
    ) -> TaskResult:
        async with self._semaphore:
            tr = TaskResult(task_id=task_id, command=command, started_at=datetime.now())
            try:
                if self._agent_factory is None:
                    raise RuntimeError("No agent_factory configured")

                from pathlib import Path

                agent = self._agent_factory()
                if skill:
                    try:
                        from ..skills import get_skill_manager

                        get_skill_manager().activate_skill(skill)
                    except Exception:
                        pass

                wd = Path(work_dir) if work_dir else None
                result = await asyncio.wait_for(
                    agent.run(command, work_dir=wd, stream=False, show_progress=False),
                    timeout=timeout,
                )
                tr.result = str(result)[:2000]

            except asyncio.TimeoutError:
                tr.error = f"Task timed out after {timeout}s"
                logger.error("Task %s timed out", task_id)
            except Exception as exc:
                tr.error = str(exc)
                logger.error("Task %s failed: %s", task_id, exc)
            finally:
                tr.finished_at = datetime.now()
                if tr.started_at:
                    tr.duration_seconds = (tr.finished_at - tr.started_at).total_seconds()
                self._history.append(tr)

            return tr

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def history(self) -> list[TaskResult]:
        return list(self._history)

    def get_active_ids(self) -> list[str]:
        return list(self._active.keys())

    async def cancel(self, task_id: str) -> bool:
        task = self._active.get(task_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def cancel_all(self) -> int:
        cancelled = 0
        for task in self._active.values():
            if not task.done():
                task.cancel()
                cancelled += 1
        return cancelled
