"""Daemon configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HeartbeatConfig:
    """Heartbeat monitor configuration."""

    enabled: bool = True
    interval: int = 60  # seconds
    unhealthy_threshold: int = 3
    check_memory: bool = True
    check_disk: bool = True
    max_memory_mb: int = 512


@dataclass
class CronJobConfig:
    """Configuration for a single cron job (from config file)."""

    name: str = ""
    schedule: str = "*/15 * * * *"
    command: str = ""
    skill: str | None = None
    enabled: bool = True
    notify: bool = True
    timeout: int = 300
    work_dir: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class SchedulerConfig:
    """Cron scheduler configuration."""

    enabled: bool = True
    timezone: str = "UTC"
    max_concurrent_jobs: int = 3
    job_timeout: int = 300
    jobs: list[CronJobConfig] = field(default_factory=list)


@dataclass
class ReactorConfig:
    """Event reactor configuration."""

    enabled: bool = False
    listen_port: int = 4097
    github_webhook_secret: str = ""


@dataclass
class DaemonConfig:
    """Top-level daemon configuration."""

    enabled: bool = True
    pid_file: str = str(Path.home() / ".config" / "amcp" / "amcp.pid")
    log_file: str = str(Path.home() / ".config" / "amcp" / "logs" / "daemon.log")
    log_level: str = "info"
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    reactor: ReactorConfig = field(default_factory=ReactorConfig)
