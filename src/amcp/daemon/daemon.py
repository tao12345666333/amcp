"""AMCPDaemon — main daemon process lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..event_bus import Event, EventType, get_event_bus
from .config import DaemonConfig
from .heartbeat import HeartbeatMonitor
from .reactor import EventReactor
from .scheduler import CronScheduler
from .task_runner import TaskRunner

logger = logging.getLogger(__name__)


class AMCPDaemon:
    """Main AMCP daemon process.

    Orchestrates:
    - HeartbeatMonitor (health checks)
    - CronScheduler (scheduled jobs)
    - EventReactor (webhook triggers)
    - TaskRunner (managed agent pool)
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

    async def start(self, *, foreground: bool = True) -> None:
        """Start all daemon components.

        Args:
            foreground: If True, run in the current process. If False,
                        fork to background (Unix-only).
        """
        if not foreground:
            self._daemonize()

        self._running = True
        self._started_at = datetime.now()

        # Setup logging
        self._setup_logging()

        # Write PID file
        self._write_pid()

        bus = get_event_bus()

        # 1. Task runner
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

        # Setup signal handlers
        self._setup_signals()

        await bus.emit(
            Event(
                type=EventType.DAEMON_STARTED,
                source="daemon",
                data={"pid": os.getpid(), "started_at": self._started_at.isoformat()},
            )
        )

        # Log to memory
        try:
            from ..memory import get_memory_manager

            mem = get_memory_manager()
            mem.append_history(
                "AMCP Daemon started",
                session_id="daemon",
                tags=["daemon", "lifecycle"],
            )
        except Exception:
            pass

        logger.info("AMCP Daemon started (PID %d)", os.getpid())

        if foreground:
            # Keep the daemon alive
            try:
                while self._running:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            finally:
                await self.stop()

    async def stop(self) -> None:
        """Gracefully stop all components."""
        self._running = False

        if self.scheduler:
            await self.scheduler.stop()
        if self.heartbeat:
            await self.heartbeat.stop()
        if self.reactor:
            await self.reactor.stop()
        if self.task_runner:
            await self.task_runner.cancel_all()

        self._remove_pid()

        bus = get_event_bus()
        await bus.emit(
            Event(
                type=EventType.DAEMON_STOPPED,
                source="daemon",
                data={"stopped_at": datetime.now().isoformat()},
            )
        )

        try:
            from ..memory import get_memory_manager

            mem = get_memory_manager()
            mem.append_history(
                "AMCP Daemon stopped",
                session_id="daemon",
                tags=["daemon", "lifecycle"],
            )
        except Exception:
            pass

        logger.info("AMCP Daemon stopped")

    # ------------------------------------------------------------------
    # PID file management
    # ------------------------------------------------------------------

    def _write_pid(self) -> None:
        pid_file = Path(self.config.pid_file).expanduser()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))
        logger.debug("Wrote PID %d to %s", os.getpid(), pid_file)

    def _remove_pid(self) -> None:
        pid_file = Path(self.config.pid_file).expanduser()
        pid_file.unlink(missing_ok=True)

    @classmethod
    def read_pid(cls, config: DaemonConfig | None = None) -> int | None:
        """Read the daemon PID from the PID file."""
        cfg = config or DaemonConfig()
        pid_file = Path(cfg.pid_file).expanduser()
        if pid_file.exists():
            try:
                return int(pid_file.read_text().strip())
            except (ValueError, OSError):
                return None
        return None

    @classmethod
    def is_running(cls, config: DaemonConfig | None = None) -> bool:
        """Check if a daemon process is currently running."""
        pid = cls.read_pid(config)
        if pid is None:
            return False
        try:
            os.kill(pid, 0)  # Signal 0 checks existence
            return True
        except (OSError, ProcessLookupError):
            return False

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _setup_signals(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(
                    sig,
                    lambda: asyncio.create_task(self.stop()),
                )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _setup_logging(self) -> None:
        log_path = Path(self.config.log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        level = getattr(logging, self.config.log_level.upper(), logging.INFO)
        handler = logging.FileHandler(str(log_path))
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

        root_logger = logging.getLogger("amcp")
        root_logger.addHandler(handler)
        root_logger.setLevel(level)

    # ------------------------------------------------------------------
    # Daemonize (Unix only)
    # ------------------------------------------------------------------

    def _daemonize(self) -> None:
        """Classic Unix double-fork to daemonize the process."""
        if sys.platform == "win32":
            logger.warning("Daemonizing not supported on Windows, running in foreground")
            return

        # First fork
        pid = os.fork()
        if pid > 0:
            # Parent exits
            sys.exit(0)

        # Create new session
        os.setsid()

        # Second fork
        pid = os.fork()
        if pid > 0:
            sys.exit(0)

        # Redirect stdio to /dev/null
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)

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

    def get_status(self) -> dict[str, Any]:
        """Return a summary of daemon status."""
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
