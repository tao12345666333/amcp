"""In-process assistant schedulers for Telegram mode.

Scans discovered skills for ``triggers.schedule`` cron expressions and runs
user-configured Telegram scheduled prompts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from croniter import croniter

from ..memory import CONFIG_DIR

if TYPE_CHECKING:
    from ..agent import Agent
    from ..skills import SkillManager, SkillMetadata, SkillTrigger

logger = logging.getLogger(__name__)

SILENT_MARKER = "[SILENT]"
SCHEDULE_STORE_VERSION = 1


@dataclass(frozen=True)
class ScheduleBlueprint:
    """Reusable prompt template for scheduled Telegram jobs."""

    name: str
    description: str
    prompt: str


SCHEDULE_BLUEPRINTS: dict[str, ScheduleBlueprint] = {
    "heartbeat": ScheduleBlueprint(
        name="heartbeat",
        description="Review open context and only notify when attention is needed.",
        prompt=(
            "Run a proactive assistant heartbeat. Review durable memory and recent session context for "
            "unresolved commitments, blockers, deadlines, or important follow-ups. If there is nothing "
            f"useful to tell the user, reply exactly {SILENT_MARKER}. Otherwise send a concise actionable "
            "update."
        ),
    ),
    "hackernews_daily": ScheduleBlueprint(
        name="hackernews_daily",
        description="Fetch and summarize the current Hacker News hotlist.",
        prompt=(
            "Fetch today's Hacker News front page or top stories using live web tools. Summarize the "
            "most important 5 to 10 items with title, URL, and why each item matters. Prefer Chinese if "
            "the user's recent Telegram conversation is Chinese. If Hacker News cannot be reached, "
            "briefly explain the failure."
        ),
    ),
}


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _parse_datetime(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=fallback.tzinfo)
    return parsed


def _validate_cron(schedule: str) -> None:
    if not croniter.is_valid(schedule):
        raise ValueError(f"Invalid cron expression: {schedule}")


@dataclass
class TelegramScheduledPrompt:
    """A persistent scheduled prompt targeting one Telegram chat."""

    id: str
    chat_id: int
    schedule: str
    prompt: str
    name: str | None = None
    enabled: bool = True
    notify: bool = True
    timeout: int = 900
    blueprint: str | None = None
    created_at: str = ""
    last_run_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TelegramScheduledPrompt:
        return cls(
            id=str(data["id"]),
            chat_id=int(data["chat_id"]),
            schedule=str(data["schedule"]),
            prompt=str(data["prompt"]),
            name=str(data["name"]) if data.get("name") else None,
            enabled=bool(data.get("enabled", True)),
            notify=bool(data.get("notify", True)),
            timeout=int(data.get("timeout", 900)),
            blueprint=str(data["blueprint"]) if data.get("blueprint") else None,
            created_at=str(data.get("created_at") or _local_now().isoformat()),
            last_run_at=str(data["last_run_at"]) if data.get("last_run_at") else None,
        )


class TelegramScheduleStore:
    """JSON-backed scheduled prompt store for Telegram."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        now_factory: Callable[[], datetime] = _local_now,
    ) -> None:
        self._path = path or CONFIG_DIR / "telegram_schedules.json"
        self._now_factory = now_factory

    @property
    def path(self) -> Path:
        return self._path

    def list_jobs(self, chat_id: int | None = None) -> list[TelegramScheduledPrompt]:
        jobs = self._load()
        if chat_id is not None:
            jobs = [job for job in jobs if job.chat_id == chat_id]
        return sorted(jobs, key=lambda job: (job.chat_id, job.created_at, job.id))

    def create_job(
        self,
        *,
        chat_id: int,
        schedule: str,
        prompt: str,
        name: str | None = None,
        notify: bool = True,
        timeout: int = 900,
        blueprint: str | None = None,
    ) -> TelegramScheduledPrompt:
        schedule = schedule.strip()
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("Prompt cannot be empty.")
        _validate_cron(schedule)
        if timeout < 1:
            raise ValueError("Timeout must be >= 1.")

        now = self._now_factory().isoformat()
        job = TelegramScheduledPrompt(
            id=uuid4().hex[:12],
            chat_id=chat_id,
            schedule=schedule,
            prompt=prompt,
            name=name.strip() if name else None,
            enabled=True,
            notify=notify,
            timeout=timeout,
            blueprint=blueprint,
            created_at=now,
            last_run_at=now,
        )
        jobs = self._load()
        jobs.append(job)
        self._save(jobs)
        return job

    def create_blueprint_job(
        self,
        *,
        chat_id: int,
        blueprint: str,
        schedule: str,
        name: str | None = None,
        notify: bool = True,
        timeout: int = 900,
    ) -> TelegramScheduledPrompt:
        blueprint_key = blueprint.strip().lower()
        template = SCHEDULE_BLUEPRINTS.get(blueprint_key)
        if template is None:
            available = ", ".join(sorted(SCHEDULE_BLUEPRINTS))
            raise ValueError(f"Unknown blueprint: {blueprint}. Available: {available}")
        return self.create_job(
            chat_id=chat_id,
            schedule=schedule,
            prompt=template.prompt,
            name=name or template.name,
            notify=notify,
            timeout=timeout,
            blueprint=template.name,
        )

    def delete_job(self, chat_id: int, job_id: str) -> bool:
        jobs = self._load()
        kept = [job for job in jobs if not (job.chat_id == chat_id and job.id == job_id)]
        if len(kept) == len(jobs):
            return False
        self._save(kept)
        return True

    def update_last_run(self, job_id: str, when: datetime | None = None) -> None:
        jobs = self._load()
        stamp = (when or self._now_factory()).isoformat()
        for job in jobs:
            if job.id == job_id:
                job.last_run_at = stamp
                self._save(jobs)
                return

    def _load(self) -> list[TelegramScheduledPrompt]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to load Telegram schedules from %s", self._path)
            return []
        items = raw.get("jobs", []) if isinstance(raw, dict) else []
        jobs: list[TelegramScheduledPrompt] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                jobs.append(TelegramScheduledPrompt.from_dict(item))
            except (KeyError, TypeError, ValueError):
                logger.warning("Skipping invalid Telegram scheduled prompt: %r", item)
        return jobs

    def _save(self, jobs: list[TelegramScheduledPrompt]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEDULE_STORE_VERSION,
            "jobs": [asdict(job) for job in jobs],
        }
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self._path)


class TelegramPromptScheduler:
    """In-process scheduler for persistent Telegram prompt jobs."""

    def __init__(
        self,
        *,
        store: TelegramScheduleStore,
        agent_factory: Callable[[str], Agent],
        send_chat: Callable[[int, str], object],
        bind_agent_context: Callable[[int, Agent], None] | None = None,
        work_dir: Path | None = None,
        tick_interval: float = 60.0,
        now_factory: Callable[[], datetime] = _local_now,
    ) -> None:
        self._store = store
        self._agent_factory = agent_factory
        self._send_chat = send_chat
        self._bind_agent_context = bind_agent_context
        self._work_dir = work_dir
        self._tick_interval = tick_interval
        self._now_factory = now_factory
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._active_jobs: set[str] = set()

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the scheduled prompt loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("TelegramPromptScheduler started")

    async def stop(self) -> None:
        """Stop the scheduled prompt loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("TelegramPromptScheduler stopped")

    async def _loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self._tick_interval)
                if not self._running:
                    break
                await self._tick()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("TelegramPromptScheduler loop crashed")

    async def _tick(self) -> None:
        """Run all due scheduled prompt jobs."""
        now = self._now_factory()
        for job in self._store.list_jobs():
            if not job.enabled or job.id in self._active_jobs:
                continue
            if self._is_due(job, now):
                await self._execute_job(job, now)

    def _is_due(self, job: TelegramScheduledPrompt, now: datetime) -> bool:
        base = _parse_datetime(job.last_run_at or job.created_at, now)
        try:
            next_run = croniter(job.schedule, base).get_next(datetime)
        except (ValueError, KeyError):
            logger.warning("Invalid cron expression %r for scheduled prompt %s", job.schedule, job.id)
            return False
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=now.tzinfo)
        return next_run <= now

    async def _execute_job(self, job: TelegramScheduledPrompt, now: datetime) -> None:
        self._active_jobs.add(job.id)
        self._store.update_last_run(job.id, now)
        try:
            agent = self._agent_factory(f"telegram-scheduled-{job.id}")
            if self._bind_agent_context is not None:
                self._bind_agent_context(job.chat_id, agent)
            result = await asyncio.wait_for(
                agent.run(
                    user_input=self._build_prompt(job, now),
                    work_dir=self._work_dir,
                    stream=False,
                    show_progress=False,
                ),
                timeout=job.timeout,
            )
        except TimeoutError:
            logger.warning("Scheduled prompt %s timed out after %ds", job.id, job.timeout)
            if job.notify:
                await self._send(job.chat_id, f"Scheduled task {self._label(job)} timed out after {job.timeout}s.")
            return
        except Exception:
            logger.exception("Scheduled prompt %s failed", job.id)
            if job.notify:
                await self._send(job.chat_id, f"Scheduled task {self._label(job)} failed. Check logs for details.")
            return
        finally:
            self._active_jobs.discard(job.id)

        text = str(result or "").strip()
        if not text or text.startswith(SILENT_MARKER):
            return
        if job.notify:
            await self._send(job.chat_id, f"Scheduled task {self._label(job)}:\n{text[:3000]}")

    def _build_prompt(self, job: TelegramScheduledPrompt, now: datetime) -> str:
        metadata = {
            "channel": "telegram",
            "source": "scheduled_prompt",
            "chat_id": str(job.chat_id),
            "job_id": job.id,
            "job_name": job.name,
            "schedule": job.schedule,
            "blueprint": job.blueprint,
            "run_at": now.isoformat(),
            "network_tools": ["web_search", "web_fetch"],
        }
        return (
            "[Telegram scheduled prompt]\n"
            "You are running inside AMCP's internal cron loop. Use live web tools for current "
            f"information. If no user-visible update is needed, reply exactly {SILENT_MARKER}.\n\n"
            f"{job.prompt}\n———————\n{json.dumps(metadata, ensure_ascii=False)}"
        )

    async def _send(self, chat_id: int, text: str) -> None:
        try:
            ret = self._send_chat(chat_id, text)
            if asyncio.iscoroutine(ret):
                await ret
        except Exception:
            logger.exception("Failed to send scheduled Telegram prompt result")

    @staticmethod
    def _label(job: TelegramScheduledPrompt) -> str:
        return f"*{job.name or job.id}*"


class AssistantScheduler:
    """In-process scheduler for skill triggers in Telegram assistant mode.

    Scans discovered skills for schedule triggers and executes them
    using croniter for cron expression matching.
    """

    def __init__(
        self,
        *,
        skill_manager: SkillManager,
        agent_factory: Callable[[str], Agent],
        send_notification: Callable[[str], object],
        work_dir: Path | None = None,
        tick_interval: float = 60.0,
    ) -> None:
        self._skill_manager = skill_manager
        self._agent_factory = agent_factory
        self._send_notification = send_notification
        self._work_dir = work_dir
        self._tick_interval = tick_interval
        self._last_run: dict[str, datetime] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return
        self._running = True
        now = datetime.now(UTC)
        for skill in self._skill_manager.get_triggered_skills():
            for i, trigger in enumerate(skill.triggers):
                if trigger.schedule:
                    key = self._trigger_key(skill.name, i)
                    self._last_run[key] = now
        self._task = asyncio.create_task(self._loop())
        logger.info("AssistantScheduler started (%d triggers)", len(self._last_run))

    async def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("AssistantScheduler stopped")

    async def _loop(self) -> None:
        """Main scheduler loop — ticks every ``tick_interval`` seconds."""
        try:
            while self._running:
                await asyncio.sleep(self._tick_interval)
                if not self._running:
                    break
                await self._tick()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("AssistantScheduler loop crashed")

    async def _tick(self) -> None:
        """Check all triggered skills and run any that are due."""
        now = datetime.now(UTC)
        for skill in self._skill_manager.get_triggered_skills():
            for i, trigger in enumerate(skill.triggers):
                if not trigger.schedule:
                    continue
                key = self._trigger_key(skill.name, i)
                last = self._last_run.get(key)
                if last is None:
                    self._last_run[key] = now
                    continue
                try:
                    next_run = croniter(trigger.schedule, last).get_next(datetime)
                    if next_run.tzinfo is None:
                        next_run = next_run.replace(tzinfo=UTC)
                except (ValueError, KeyError):
                    logger.warning(
                        "Invalid cron expression %r for skill %s",
                        trigger.schedule,
                        skill.name,
                    )
                    continue
                if next_run <= now:
                    await self._execute_trigger(skill, trigger, key)

    async def _execute_trigger(
        self,
        skill: SkillMetadata,
        trigger: SkillTrigger,
        key: str,
    ) -> None:
        """Execute a single trigger and optionally send notification."""
        logger.info("Scheduler executing trigger %s: %s", key, trigger.command)
        self._last_run[key] = datetime.now(UTC)
        session_id = f"scheduler-{skill.name}"
        try:
            agent = self._agent_factory(session_id)
            work_dir = Path(trigger.work_dir) if trigger.work_dir else self._work_dir
            result = await asyncio.wait_for(
                agent.run(
                    user_input=trigger.command,
                    work_dir=work_dir,
                    stream=False,
                    show_progress=False,
                ),
                timeout=trigger.timeout,
            )
        except TimeoutError:
            logger.warning("Trigger %s timed out after %ds", key, trigger.timeout)
            if trigger.notify:
                await self._notify(f"⏰ Scheduled skill *{skill.name}* timed out after {trigger.timeout}s.")
            return
        except Exception:
            logger.exception("Trigger %s failed", key)
            if trigger.notify:
                await self._notify(f"❌ Scheduled skill *{skill.name}* failed. Check logs for details.")
            return

        if trigger.notify and result:
            await self._notify(f"📋 Scheduled skill *{skill.name}*:\n{result[:3000]}")

    async def _notify(self, text: str) -> None:
        """Send a notification, handling both sync and async callables."""
        try:
            ret = self._send_notification(text)
            if asyncio.iscoroutine(ret):
                await ret
        except Exception:
            logger.exception("Failed to send scheduler notification")

    @staticmethod
    def _trigger_key(skill_name: str, index: int) -> str:
        return f"{skill_name}:{index}"
