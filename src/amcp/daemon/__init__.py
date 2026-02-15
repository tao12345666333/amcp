"""AMCP Background Services — Heartbeat + Cron + Reactor.

Provides application-level background services that can be embedded
into ``amcp serve`` or run standalone.  Process lifecycle (PID, logging,
restart) should be handled by the deployment platform (Docker, systemd, etc.).

Components:
- BackgroundServices: lightweight orchestrator
- HeartbeatMonitor: periodic health checks
- CronScheduler: cron-style task scheduling
- EventReactor: webhook/event-driven triggers
- TaskRunner: managed agent execution pool
"""

from .config import DaemonConfig, HeartbeatConfig, ReactorConfig, SchedulerConfig
from .daemon import BackgroundServices
from .heartbeat import HealthStatus, HeartbeatMonitor
from .scheduler import CronJob, CronScheduler
from .task_runner import TaskRunner

__all__ = [
    "BackgroundServices",
    "HeartbeatMonitor",
    "HealthStatus",
    "CronScheduler",
    "CronJob",
    "TaskRunner",
    "DaemonConfig",
    "HeartbeatConfig",
    "SchedulerConfig",
    "ReactorConfig",
]
