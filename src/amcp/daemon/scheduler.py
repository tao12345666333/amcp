"""CronScheduler — cron-style task scheduling for the AMCP daemon."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..event_bus import Event, EventType, get_event_bus
from .config import CronJobConfig, SchedulerConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shortcut expansions
# ---------------------------------------------------------------------------

_SHORTCUTS: dict[str, str] = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}

_EVERY_RE = re.compile(r"^@every\s+(\d+)([mhd])$", re.IGNORECASE)


def _expand_schedule(expr: str) -> str:
    """Expand shortcut expressions into standard 5-field cron."""
    expr = expr.strip()
    if expr in _SHORTCUTS:
        return _SHORTCUTS[expr]

    m = _EVERY_RE.match(expr)
    if m:
        val, unit = int(m.group(1)), m.group(2).lower()
        unit_map = {
            "m": f"*/{val} * * * *",
            "h": f"0 */{val} * * *",
            "d": f"0 0 */{val} * *",
        }
        return unit_map.get(unit, expr)

    return expr


# ---------------------------------------------------------------------------
# CronJob
# ---------------------------------------------------------------------------


@dataclass
class CronJob:
    """A scheduled job with runtime state."""

    name: str
    schedule: str  # cron expression (after expansion)
    command: str  # Prompt to send to the agent
    skill: str | None = None
    enabled: bool = True
    notify: bool = True
    timeout: int = 300
    work_dir: str | None = None
    tags: list[str] = field(default_factory=list)

    # Runtime tracking
    last_run: datetime | None = None
    last_result: str | None = None
    last_status: str = "idle"  # idle | running | success | failed
    run_count: int = 0
    failure_count: int = 0

    @classmethod
    def from_config(cls, cfg: CronJobConfig) -> CronJob:
        return cls(
            name=cfg.name,
            schedule=_expand_schedule(cfg.schedule),
            command=cfg.command,
            skill=cfg.skill,
            enabled=cfg.enabled,
            notify=cfg.notify,
            timeout=cfg.timeout,
            work_dir=cfg.work_dir,
            tags=list(cfg.tags),
        )


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------


class CronScheduler:
    """Cron-style task scheduler.

    Runs a background loop that checks every 30 s whether any job's schedule
    matches the current time. Matching jobs are dispatched via an
    *agent_factory* callback which should return an awaitable producing a
    string result (e.g. ``Agent.run(…)``).
    """

    def __init__(
        self,
        config: SchedulerConfig | None = None,
        *,
        agent_factory: Callable[..., Any] | None = None,
    ):
        self.config = config or SchedulerConfig()
        self.jobs: dict[str, CronJob] = {}
        self._agent_factory = agent_factory
        self._running = False
        self._task: asyncio.Task | None = None
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._tz = self._resolve_timezone()

    # ------------------------------------------------------------------
    # Timezone
    # ------------------------------------------------------------------

    def _resolve_timezone(self):
        """Resolve timezone from config."""
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(self.config.timezone)
        except Exception:
            return UTC

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("CronScheduler started (%d jobs loaded)", len(self.jobs))

    async def stop(self) -> None:
        self._running = False
        # Cancel running job tasks
        for job_name, task in list(self._active_tasks.items()):
            if not task.done():
                task.cancel()
                logger.info("Cancelled running job: %s", job_name)
        self._active_tasks.clear()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("CronScheduler stopped")

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------

    def add_job(self, job: CronJob) -> None:
        self.jobs[job.name] = job
        logger.info("Added job: %s schedule=%s", job.name, job.schedule)

    def remove_job(self, name: str) -> bool:
        if name in self.jobs:
            del self.jobs[name]
            return True
        return False

    def enable_job(self, name: str) -> bool:
        if name in self.jobs:
            self.jobs[name].enabled = True
            return True
        return False

    def disable_job(self, name: str) -> bool:
        if name in self.jobs:
            self.jobs[name].enabled = False
            return True
        return False

    def load_jobs_from_config(self) -> None:
        """Load jobs from the scheduler config."""
        for job_cfg in self.config.jobs:
            job = CronJob.from_config(job_cfg)
            self.add_job(job)

    # ------------------------------------------------------------------
    # Schedule checking
    # ------------------------------------------------------------------

    def _should_run(self, job: CronJob, now: datetime) -> bool:
        """Determine whether *job* should run at *now*."""
        try:
            from croniter import croniter
        except ImportError:
            logger.warning("croniter not installed — cron scheduling disabled")
            return False

        if job.last_status == "running":
            return False

        cron = croniter(job.schedule, now)
        prev = cron.get_prev(datetime)
        # The job should run if the previous scheduled time is within the last
        # check window (30 s) and hasn't been run since then.
        if job.last_run is None:
            return (now - prev).total_seconds() < 60
        return prev > job.last_run

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            try:
                now = datetime.now(self._tz)
                # Garbage-collect finished tasks
                finished = [n for n, t in self._active_tasks.items() if t.done()]
                for n in finished:
                    del self._active_tasks[n]

                for job in self.jobs.values():
                    if not job.enabled:
                        continue
                    if len(self._active_tasks) >= self.config.max_concurrent_jobs:
                        break
                    if self._should_run(job, now):
                        task = asyncio.create_task(self._execute_job(job))
                        self._active_tasks[job.name] = task
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in scheduler loop")

            await asyncio.sleep(30)

    # ------------------------------------------------------------------
    # Job execution
    # ------------------------------------------------------------------

    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single cron job."""
        job.last_run = datetime.now(self._tz)
        job.last_status = "running"
        bus = get_event_bus()

        await bus.emit(
            Event(
                type=EventType.CRON_JOB_STARTED,
                source=f"cron:{job.name}",
                data={"job_name": job.name, "command": job.command},
            )
        )

        try:
            if self._agent_factory is None:
                raise RuntimeError("No agent_factory configured for CronScheduler")

            result = await asyncio.wait_for(
                self._run_agent(job),
                timeout=job.timeout,
            )

            job.last_result = str(result)[:2000]
            job.last_status = "success"
            job.run_count += 1

            # Log to memory
            try:
                from ..memory import get_memory_manager

                mem = get_memory_manager()
                mem.append_history(
                    content=f"[Cron:{job.name}] {job.last_result[:500]}",
                    session_id="daemon",
                    tags=["cron", job.name, *job.tags],
                )
            except Exception:
                pass

            await bus.emit(
                Event(
                    type=EventType.CRON_JOB_COMPLETED,
                    source=f"cron:{job.name}",
                    data={
                        "job_name": job.name,
                        "result": job.last_result[:500],
                        "run_count": job.run_count,
                    },
                )
            )

            if job.notify:
                await self._notify(job, job.last_result)

            logger.info("Job %s completed successfully (run #%d)", job.name, job.run_count)

        except TimeoutError:
            job.last_status = "failed"
            job.failure_count += 1
            logger.error("Job %s timed out after %ds", job.name, job.timeout)
            await bus.emit(
                Event(
                    type=EventType.CRON_JOB_FAILED,
                    source=f"cron:{job.name}",
                    data={"job_name": job.name, "error": "timeout"},
                )
            )

        except Exception as exc:
            job.last_status = "failed"
            job.failure_count += 1
            logger.error("Job %s failed: %s", job.name, exc)
            await bus.emit(
                Event(
                    type=EventType.CRON_JOB_FAILED,
                    source=f"cron:{job.name}",
                    data={"job_name": job.name, "error": str(exc)},
                )
            )

    async def _run_agent(self, job: CronJob) -> str:
        """Create an agent and run the job command."""
        from pathlib import Path

        agent = self._agent_factory()
        if job.skill:
            try:
                from ..skills import get_skill_manager

                sm = get_skill_manager()
                sm.activate_skill(job.skill)
            except Exception:
                logger.warning("Could not activate skill %s for job %s", job.skill, job.name)

        work_dir = Path(job.work_dir) if job.work_dir else None
        return await agent.run(job.command, work_dir=work_dir, stream=False, show_progress=False)

    async def _notify(self, job: CronJob, result: str) -> None:
        """Send notification (Telegram if available)."""
        try:
            from ..telegram.bot import get_telegram_bot

            bot = get_telegram_bot()
            if bot:
                msg = f"🕐 *Cron job completed*: `{job.name}`\n\n{result[:500]}"
                await bot.send_notification(msg)
        except Exception:
            logger.debug("Telegram notification skipped for job %s", job.name)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def active_job_count(self) -> int:
        return len(self._active_tasks)

    @property
    def is_running(self) -> bool:
        return self._running

    def get_jobs_summary(self) -> list[dict[str, Any]]:
        """Return a list of dicts summarising each job."""
        result = []
        for job in self.jobs.values():
            next_run = self._next_run_str(job)
            result.append(
                {
                    "name": job.name,
                    "schedule": job.schedule,
                    "enabled": job.enabled,
                    "last_status": job.last_status,
                    "last_run": job.last_run.isoformat() if job.last_run else None,
                    "next_run": next_run,
                    "run_count": job.run_count,
                    "failure_count": job.failure_count,
                }
            )
        return result

    def _next_run_str(self, job: CronJob) -> str | None:
        """Human-readable time until next run."""
        try:
            from croniter import croniter

            now = datetime.now(self._tz)
            cron = croniter(job.schedule, now)
            nxt = cron.get_next(datetime)
            delta = nxt - now
            total = int(delta.total_seconds())
            if total < 60:
                return f"in {total}s"
            elif total < 3600:
                return f"in {total // 60}m"
            else:
                return f"in {total // 3600}h {(total % 3600) // 60}m"
        except Exception:
            return None
