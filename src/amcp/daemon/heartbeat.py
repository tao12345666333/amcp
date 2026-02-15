"""HeartbeatMonitor — periodic health checks for the AMCP daemon."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..event_bus import Event, EventType, get_event_bus
from .config import HeartbeatConfig

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Daemon health status snapshot."""

    healthy: bool
    uptime_seconds: float
    memory_usage_mb: float
    disk_free_mb: float
    active_jobs: int
    active_sessions: int
    last_heartbeat: datetime
    checks: dict[str, bool] = field(default_factory=dict)
    error_details: dict[str, str] = field(default_factory=dict)


class HeartbeatMonitor:
    """Monitor daemon health with periodic checks.

    Emits events through the EventBus:
    - HEARTBEAT: on each successful heartbeat
    - HEALTH_CHECK_FAILED: when a check fails
    - DAEMON_RECOVERED: when recovering from unhealthy state
    """

    def __init__(
        self,
        config: HeartbeatConfig | None = None,
        *,
        active_jobs_fn: asyncio.coroutines | None = None,
        active_sessions_fn: asyncio.coroutines | None = None,
    ):
        self.config = config or HeartbeatConfig()
        self._running = False
        self._start_time = time.monotonic()
        self._consecutive_failures = 0
        self._was_unhealthy = False
        self._last_status: HealthStatus | None = None
        self._task: asyncio.Task | None = None

        # Callbacks to query runtime state
        self._active_jobs_fn = active_jobs_fn
        self._active_sessions_fn = active_sessions_fn

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the heartbeat loop."""
        if self._running:
            return
        self._running = True
        self._start_time = time.monotonic()
        self._task = asyncio.create_task(self._loop())
        logger.info("HeartbeatMonitor started (interval=%ds)", self.config.interval)

    async def stop(self) -> None:
        """Stop the heartbeat loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("HeartbeatMonitor stopped")

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            try:
                status = await self.check_health()
                self._last_status = status

                bus = get_event_bus()

                if status.healthy:
                    self._consecutive_failures = 0
                    await bus.emit(
                        Event(
                            type=EventType.HEARTBEAT,
                            source="heartbeat",
                            data={"status": "healthy", "uptime": status.uptime_seconds},
                        )
                    )
                    if self._was_unhealthy:
                        self._was_unhealthy = False
                        await bus.emit(
                            Event(
                                type=EventType.DAEMON_RECOVERED,
                                source="heartbeat",
                                data={"recovered_at": datetime.now().isoformat()},
                            )
                        )
                        logger.info("Daemon recovered from unhealthy state")
                else:
                    self._consecutive_failures += 1
                    self._was_unhealthy = True
                    await bus.emit(
                        Event(
                            type=EventType.HEALTH_CHECK_FAILED,
                            source="heartbeat",
                            data={
                                "checks": status.checks,
                                "errors": status.error_details,
                                "consecutive_failures": self._consecutive_failures,
                            },
                        )
                    )
                    logger.warning(
                        "Health check failed (%d/%d): %s",
                        self._consecutive_failures,
                        self.config.unhealthy_threshold,
                        status.error_details,
                    )

                    if self._consecutive_failures >= self.config.unhealthy_threshold:
                        await self._on_unhealthy(status)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error in heartbeat loop")

            await asyncio.sleep(self.config.interval)

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def check_health(self) -> HealthStatus:
        """Run all health checks and return a status snapshot."""
        checks: dict[str, bool] = {}
        errors: dict[str, str] = {}

        # Memory check
        mem_mb = 0.0
        if self.config.check_memory:
            try:
                mem_mb = self._check_memory()
                ok = mem_mb < self.config.max_memory_mb
                checks["memory_available"] = ok
                if not ok:
                    errors["memory_available"] = f"Usage {mem_mb:.0f} MB > limit {self.config.max_memory_mb} MB"
            except Exception as exc:
                checks["memory_available"] = False
                errors["memory_available"] = str(exc)

        # Disk check
        disk_free = 0.0
        if self.config.check_disk:
            try:
                disk_free = self._check_disk()
                ok = disk_free > 100  # at least 100 MB free
                checks["disk_space"] = ok
                if not ok:
                    errors["disk_space"] = f"Only {disk_free:.0f} MB free"
            except Exception as exc:
                checks["disk_space"] = False
                errors["disk_space"] = str(exc)

        # Active jobs / sessions (delegated to runtime callbacks)
        active_jobs = 0
        if self._active_jobs_fn:
            with contextlib.suppress(Exception):
                active_jobs = self._active_jobs_fn()

        active_sessions = 0
        if self._active_sessions_fn:
            with contextlib.suppress(Exception):
                active_sessions = self._active_sessions_fn()

        uptime = time.monotonic() - self._start_time
        healthy = all(checks.values()) if checks else True

        return HealthStatus(
            healthy=healthy,
            uptime_seconds=uptime,
            memory_usage_mb=mem_mb,
            disk_free_mb=disk_free,
            active_jobs=active_jobs,
            active_sessions=active_sessions,
            last_heartbeat=datetime.now(),
            checks=checks,
            error_details=errors,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_memory() -> float:
        """Return current process memory usage in MB."""
        try:
            import psutil

            proc = psutil.Process(os.getpid())
            return proc.memory_info().rss / (1024 * 1024)
        except ImportError:
            # Fallback: read /proc on Linux
            try:
                with open(f"/proc/{os.getpid()}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            return int(line.split()[1]) / 1024  # kB -> MB
            except Exception:
                pass
        return 0.0

    @staticmethod
    def _check_disk() -> float:
        """Return free disk space in MB for the home directory."""
        try:
            import shutil

            usage = shutil.disk_usage(str(Path.home()))
            return usage.free / (1024 * 1024)
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    async def _on_unhealthy(self, status: HealthStatus) -> None:
        """Handle unhealthy state — log and notify."""
        logger.error(
            "Daemon unhealthy for %d consecutive checks: %s",
            self._consecutive_failures,
            status.error_details,
        )
        # In the future we could attempt self-recovery here (e.g. restarting
        # certain subsystems) or send a Telegram alert.
        # For now we reset the counter so the warning keeps firing periodically
        # rather than escalating indefinitely.
        self._consecutive_failures = 0

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def last_status(self) -> HealthStatus | None:
        return self._last_status

    @property
    def is_running(self) -> bool:
        return self._running
