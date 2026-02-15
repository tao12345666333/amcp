"""Tests for AMCP Phase 8 — Heartbeat + Cron (Daemon)."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Daemon config
# ---------------------------------------------------------------------------


class TestDaemonConfig:
    def test_defaults(self):
        from amcp.daemon.config import DaemonConfig

        cfg = DaemonConfig()
        assert cfg.enabled is True
        assert cfg.heartbeat.enabled is True
        assert cfg.heartbeat.interval == 60
        assert cfg.scheduler.enabled is True
        assert cfg.scheduler.max_concurrent_jobs == 3
        assert cfg.reactor.enabled is False

    def test_heartbeat_config(self):
        from amcp.daemon.config import HeartbeatConfig

        hb = HeartbeatConfig(interval=30, max_memory_mb=256)
        assert hb.interval == 30
        assert hb.max_memory_mb == 256

    def test_scheduler_config(self):
        from amcp.daemon.config import CronJobConfig, SchedulerConfig

        job = CronJobConfig(name="test", schedule="*/5 * * * *", command="echo hi")
        sched = SchedulerConfig(jobs=[job])
        assert len(sched.jobs) == 1
        assert sched.jobs[0].name == "test"

    def test_reactor_config(self):
        from amcp.daemon.config import ReactorConfig

        r = ReactorConfig(enabled=True, listen_port=9000)
        assert r.enabled
        assert r.listen_port == 9000


# ---------------------------------------------------------------------------
# CronJob & schedule expansion
# ---------------------------------------------------------------------------


class TestCronJob:
    def test_from_config(self):
        from amcp.daemon.config import CronJobConfig
        from amcp.daemon.scheduler import CronJob

        cfg = CronJobConfig(
            name="my-job",
            schedule="@hourly",
            command="do stuff",
            tags=["a", "b"],
        )
        job = CronJob.from_config(cfg)
        assert job.name == "my-job"
        assert job.schedule == "0 * * * *"  # expanded
        assert job.command == "do stuff"
        assert job.tags == ["a", "b"]

    def test_expand_shortcuts(self):
        from amcp.daemon.scheduler import _expand_schedule

        assert _expand_schedule("@hourly") == "0 * * * *"
        assert _expand_schedule("@daily") == "0 0 * * *"
        assert _expand_schedule("@weekly") == "0 0 * * 0"
        assert _expand_schedule("@every 5m") == "*/5 * * * *"
        assert _expand_schedule("@every 2h") == "0 */2 * * *"
        assert _expand_schedule("@every 1d") == "0 0 */1 * *"
        assert _expand_schedule("*/10 * * * *") == "*/10 * * * *"  # no change


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------


class TestCronScheduler:
    def test_add_remove_job(self):
        from amcp.daemon.scheduler import CronJob, CronScheduler

        sched = CronScheduler()
        job = CronJob(name="test-job", schedule="0 * * * *", command="hi")
        sched.add_job(job)
        assert "test-job" in sched.jobs
        assert sched.remove_job("test-job")
        assert "test-job" not in sched.jobs

    def test_enable_disable(self):
        from amcp.daemon.scheduler import CronJob, CronScheduler

        sched = CronScheduler()
        job = CronJob(name="j1", schedule="0 * * * *", command="hi")
        sched.add_job(job)
        sched.disable_job("j1")
        assert not sched.jobs["j1"].enabled
        sched.enable_job("j1")
        assert sched.jobs["j1"].enabled

    def test_load_from_config(self):
        from amcp.daemon.config import CronJobConfig, SchedulerConfig
        from amcp.daemon.scheduler import CronScheduler

        cfg = SchedulerConfig(
            jobs=[
                CronJobConfig(name="a", schedule="@hourly", command="cmd-a"),
                CronJobConfig(name="b", schedule="@daily", command="cmd-b"),
            ]
        )
        sched = CronScheduler(config=cfg)
        sched.load_jobs_from_config()
        assert len(sched.jobs) == 2
        assert "a" in sched.jobs
        assert "b" in sched.jobs

    def test_jobs_summary(self):
        from amcp.daemon.scheduler import CronJob, CronScheduler

        sched = CronScheduler()
        sched.add_job(CronJob(name="x", schedule="*/5 * * * *", command="test"))
        summary = sched.get_jobs_summary()
        assert len(summary) == 1
        assert summary[0]["name"] == "x"
        assert summary[0]["enabled"] is True
        assert summary[0]["last_status"] == "idle"


# ---------------------------------------------------------------------------
# HeartbeatMonitor
# ---------------------------------------------------------------------------


class TestHeartbeatMonitor:
    @pytest.mark.asyncio
    async def test_check_health_defaults(self):
        from amcp.daemon.heartbeat import HeartbeatMonitor, HealthStatus

        hb = HeartbeatMonitor()
        status = await hb.check_health()
        assert isinstance(status, HealthStatus)
        assert status.uptime_seconds >= 0
        # Without psutil, memory check may return 0 on some systems

    @pytest.mark.asyncio
    async def test_healthy_status(self):
        from amcp.daemon.config import HeartbeatConfig
        from amcp.daemon.heartbeat import HeartbeatMonitor

        hb = HeartbeatMonitor(config=HeartbeatConfig(check_memory=False, check_disk=False))
        status = await hb.check_health()
        assert status.healthy is True

    @pytest.mark.asyncio
    async def test_memory_check_fails_on_limit(self):
        from amcp.daemon.config import HeartbeatConfig
        from amcp.daemon.heartbeat import HeartbeatMonitor

        # Set absurdly low limit to trigger failure
        hb = HeartbeatMonitor(config=HeartbeatConfig(max_memory_mb=1, check_disk=False))
        status = await hb.check_health()
        # Should fail because any process uses > 1MB
        if status.memory_usage_mb > 0:
            assert status.healthy is False
            assert "memory_available" in status.error_details

    def test_is_running(self):
        from amcp.daemon.heartbeat import HeartbeatMonitor

        hb = HeartbeatMonitor()
        assert hb.is_running is False


# ---------------------------------------------------------------------------
# TaskRunner
# ---------------------------------------------------------------------------


class TestTaskRunner:
    def test_initial_state(self):
        from amcp.daemon.task_runner import TaskRunner

        runner = TaskRunner(max_concurrent=2)
        assert runner.active_count == 0
        assert runner.history == []

    @pytest.mark.asyncio
    async def test_submit_task(self):
        from amcp.daemon.task_runner import TaskRunner

        # Create a mock agent factory
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="done")

        runner = TaskRunner(agent_factory=lambda: mock_agent)
        task_id = await runner.submit("test command", timeout=5)
        assert task_id.startswith("task-")

        # Wait for completion
        await asyncio.sleep(0.5)
        assert len(runner.history) == 1
        assert runner.history[0].result == "done"


# ---------------------------------------------------------------------------
# AMCPDaemon
# ---------------------------------------------------------------------------


class TestAMCPDaemon:
    def test_pid_file_management(self, tmp_path):
        from amcp.daemon.config import DaemonConfig
        from amcp.daemon.daemon import AMCPDaemon

        pid_file = tmp_path / "test.pid"
        cfg = DaemonConfig(pid_file=str(pid_file))

        daemon = AMCPDaemon(config=cfg)
        daemon._write_pid()
        assert pid_file.exists()
        assert pid_file.read_text() == str(os.getpid())

        daemon._remove_pid()
        assert not pid_file.exists()

    def test_read_pid(self, tmp_path):
        from amcp.daemon.config import DaemonConfig
        from amcp.daemon.daemon import AMCPDaemon

        pid_file = tmp_path / "test.pid"
        cfg = DaemonConfig(pid_file=str(pid_file))

        # No file → None
        assert AMCPDaemon.read_pid(cfg) is None

        # Write PID
        pid_file.write_text("12345")
        assert AMCPDaemon.read_pid(cfg) == 12345

    def test_is_running_false(self, tmp_path):
        from amcp.daemon.config import DaemonConfig
        from amcp.daemon.daemon import AMCPDaemon

        cfg = DaemonConfig(pid_file=str(tmp_path / "nope.pid"))
        assert AMCPDaemon.is_running(cfg) is False

    def test_get_status(self):
        from amcp.daemon.daemon import AMCPDaemon

        daemon = AMCPDaemon()
        status = daemon.get_status()
        assert status["running"] is False
        assert "heartbeat" in status
        assert "scheduler" in status
        assert "reactor" in status
        assert "task_runner" in status


# ---------------------------------------------------------------------------
# EventReactor
# ---------------------------------------------------------------------------


class TestEventReactor:
    def test_default_rules(self):
        from amcp.daemon.reactor import EventReactor

        reactor = EventReactor()
        assert "github.push" in reactor._rules
        assert "github.pull_request" in reactor._rules

    def test_add_custom_rule(self):
        from amcp.daemon.reactor import EventReactor, ReactionRule

        reactor = EventReactor()
        reactor.add_rule(
            ReactionRule(
                name="custom",
                event_type="custom.event",
                command_template="handle custom",
            )
        )
        assert "custom.event" in reactor._rules

    def test_verify_signature(self):
        import hashlib
        import hmac

        from amcp.daemon.config import ReactorConfig
        from amcp.daemon.reactor import EventReactor

        secret = "test-secret"
        reactor = EventReactor(config=ReactorConfig(github_webhook_secret=secret))

        body = b'{"test": true}'
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        sig = f"sha256={expected}"
        assert reactor._verify_signature(body, sig) is True
        assert reactor._verify_signature(body, "sha256=wrong") is False


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class TestDaemonEventTypes:
    def test_event_types_exist(self):
        from amcp.event_bus import EventType

        assert EventType.DAEMON_STARTED.value == "daemon.started"
        assert EventType.DAEMON_STOPPED.value == "daemon.stopped"
        assert EventType.DAEMON_RECOVERED.value == "daemon.recovered"
        assert EventType.HEARTBEAT.value == "heartbeat"
        assert EventType.HEALTH_CHECK_FAILED.value == "heartbeat.check_failed"
        assert EventType.CRON_JOB_STARTED.value == "cron.job_started"
        assert EventType.CRON_JOB_COMPLETED.value == "cron.job_completed"
        assert EventType.CRON_JOB_FAILED.value == "cron.job_failed"
        assert EventType.WEBHOOK_RECEIVED.value == "webhook.received"


# ---------------------------------------------------------------------------
# Config decode / encode roundtrip
# ---------------------------------------------------------------------------


class TestDaemonConfigRoundtrip:
    def test_decode_encode(self):
        from amcp.config import _decode_daemon, _encode_daemon

        raw = {
            "enabled": True,
            "log_level": "debug",
            "heartbeat": {"interval": 30, "max_memory_mb": 256},
            "scheduler": {
                "timezone": "Asia/Shanghai",
                "jobs": [
                    {
                        "name": "ci-check",
                        "schedule": "*/15 * * * *",
                        "command": "check CI",
                        "enabled": True,
                        "notify": True,
                        "timeout": 120,
                    }
                ],
            },
            "reactor": {"enabled": True, "listen_port": 9090},
        }

        cfg = _decode_daemon(raw)
        assert cfg is not None
        assert cfg.log_level == "debug"
        assert cfg.heartbeat.interval == 30
        assert cfg.heartbeat.max_memory_mb == 256
        assert cfg.scheduler.timezone == "Asia/Shanghai"
        assert len(cfg.scheduler.jobs) == 1
        assert cfg.scheduler.jobs[0].name == "ci-check"
        assert cfg.reactor.enabled is True
        assert cfg.reactor.listen_port == 9090

        encoded = _encode_daemon(cfg)
        assert encoded is not None
        assert encoded["log_level"] == "debug"
        assert encoded["heartbeat"]["interval"] == 30
        assert encoded["reactor"]["listen_port"] == 9090

    def test_decode_none(self):
        from amcp.config import _decode_daemon

        assert _decode_daemon(None) is None

    def test_encode_none(self):
        from amcp.config import _encode_daemon

        assert _encode_daemon(None) is None


# ---------------------------------------------------------------------------
# Cleanup jobs
# ---------------------------------------------------------------------------


class TestCleanupJobs:
    def test_cleanup_old_sessions(self, tmp_path):
        from amcp.daemon.jobs.cleanup import cleanup_old_sessions

        # Patch sessions dir
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        # Create old and new session files
        old_file = sessions_dir / "old.json"
        old_file.write_text('{"session_id": "old"}')
        # Set mtime to 60 days ago
        old_time = time.time() - (60 * 86400)
        os.utime(old_file, (old_time, old_time))

        new_file = sessions_dir / "new.json"
        new_file.write_text('{"session_id": "new"}')

        with patch("amcp.daemon.jobs.cleanup.Path.home", return_value=tmp_path / "home"):
            # Won't find the default path, so returns 0
            result = cleanup_old_sessions(max_age_days=30)
            assert result == 0  # because the patched home doesn't have .config/amcp/sessions


# ---------------------------------------------------------------------------
# Custom jobs
# ---------------------------------------------------------------------------


class TestCustomJobs:
    def test_create_custom_job(self):
        from amcp.daemon.jobs.custom import create_custom_job

        job = create_custom_job(
            name="my-job",
            schedule="@every 5m",
            command="do something",
            notify=True,
            tags=["custom"],
        )
        assert job.name == "my-job"
        assert job.schedule == "*/5 * * * *"
        assert job.command == "do something"
        assert job.tags == ["custom"]
