"""BackgroundServices — lightweight orchestrator for daemon components.

This replaces the old AMCPDaemon class.  Process lifecycle (PID files,
daemonization, logging, restart) is intentionally NOT handled here — that
responsibility belongs to the deployment platform (Docker, systemd, etc.).

This module provides a simple ``BackgroundServices`` class that:
- Starts / stops the CronScheduler, EventReactor and HeartbeatMonitor
- Can be embedded into ``amcp serve`` or used standalone via ``asyncio.run``
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..event_bus import Event, EventType, get_event_bus
from .config import DaemonConfig
from .heartbeat import HeartbeatMonitor
from .reactor import EventReactor
from .scheduler import CronScheduler
from .task_runner import TaskRunner

logger = logging.getLogger(__name__)


class BackgroundServices:
    """Lightweight orchestrator for AMCP background services.

    Usage::

        svc = BackgroundServices(config=cfg, agent_factory=my_factory)
        await svc.start()   # non-blocking, spawns background tasks
        ...
        await svc.stop()    # graceful shutdown
    """

    def __init__(
        self,
        config: DaemonConfig | None = None,
        *,
        agent_factory: Callable[..., Any] | None = None,
    ):
        self.config = config or DaemonConfig()
        self._agent_factory = agent_factory
        self._running = False
        self._started_at: datetime | None = None

        # Sub-components (created in start())
        self.heartbeat: HeartbeatMonitor | None = None
        self.scheduler: CronScheduler | None = None
        self.reactor: EventReactor | None = None
        self.task_runner: TaskRunner | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start all enabled background services (non-blocking)."""
        if self._running:
            return

        self._running = True
        self._started_at = datetime.now()

        bus = get_event_bus()

        # 1. Task runner (always created — used by scheduler and reactor)
        self.task_runner = TaskRunner(
            max_concurrent=self.config.scheduler.max_concurrent_jobs,
            agent_factory=self._agent_factory,
        )

        # 2. Heartbeat
        if self.config.heartbeat.enabled:
            self.heartbeat = HeartbeatMonitor(
                config=self.config.heartbeat,
                active_jobs_fn=lambda: self.task_runner.active_count if self.task_runner else 0,
            )
            asyncio.create_task(self.heartbeat.start())

        # 3. Scheduler
        if self.config.scheduler.enabled:
            self.scheduler = CronScheduler(
                config=self.config.scheduler,
                agent_factory=self._agent_factory,
            )
            self.scheduler.load_jobs_from_config()
            asyncio.create_task(self.scheduler.start())

        # 4. Reactor
        if self.config.reactor.enabled:
            self.reactor = EventReactor(
                config=self.config.reactor,
                schedule_fn=self._schedule_from_reactor,
            )
            asyncio.create_task(self.reactor.start())

        await bus.emit(
            Event(
                type=EventType.DAEMON_STARTED,
                source="background-services",
                data={"pid": os.getpid(), "started_at": self._started_at.isoformat()},
            )
        )

        logger.info(
            "Background services started (heartbeat=%s, scheduler=%s [%d jobs], reactor=%s)",
            self.config.heartbeat.enabled,
            self.config.scheduler.enabled,
            len(self.config.scheduler.jobs),
            self.config.reactor.enabled,
        )

    async def stop(self) -> None:
        """Gracefully stop all components."""
        if not self._running:
            return

        self._running = False

        if self.scheduler:
            await self.scheduler.stop()
        if self.heartbeat:
            await self.heartbeat.stop()
        if self.reactor:
            await self.reactor.stop()
        if self.task_runner:
            await self.task_runner.cancel_all()

        bus = get_event_bus()
        await bus.emit(
            Event(
                type=EventType.DAEMON_STOPPED,
                source="background-services",
                data={"stopped_at": datetime.now().isoformat()},
            )
        )

        logger.info("Background services stopped")

    # ------------------------------------------------------------------
    # Reactor integration
    # ------------------------------------------------------------------

    async def _schedule_from_reactor(self, command: str, skill: str | None) -> None:
        """Schedule a task from the event reactor."""
        if self.task_runner:
            await self.task_runner.submit(command, skill=skill)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict[str, Any]:
        """Return a summary of service status."""
        return {
            "running": self._running,
            "pid": os.getpid(),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "heartbeat": {
                "enabled": self.heartbeat is not None,
                "healthy": self.heartbeat.last_status.healthy
                if self.heartbeat and self.heartbeat.last_status
                else None,
            },
            "scheduler": {
                "enabled": self.scheduler is not None,
                "job_count": len(self.scheduler.jobs) if self.scheduler else 0,
                "active_jobs": self.scheduler.active_job_count if self.scheduler else 0,
            },
            "reactor": {
                "enabled": self.reactor is not None and self.config.reactor.enabled,
            },
            "task_runner": {
                "active_tasks": self.task_runner.active_count if self.task_runner else 0,
            },
        }
