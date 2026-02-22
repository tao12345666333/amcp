"""In-process assistant scheduler for Telegram mode.

Scans discovered skills for ``triggers.schedule`` cron expressions and
executes them on schedule, sending results via the bot's notification system.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from croniter import croniter

if TYPE_CHECKING:
    from ..agent import Agent
    from ..skills import SkillManager, SkillMetadata, SkillTrigger

logger = logging.getLogger(__name__)


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
