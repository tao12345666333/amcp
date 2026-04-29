"""Tests for the AssistantScheduler in Telegram assistant mode."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amcp.skills import SkillManager, SkillMetadata, SkillTrigger
from amcp.telegram.scheduler import AssistantScheduler


def _make_skill(
    name: str = "heartbeat",
    schedule: str = "*/30 * * * *",
    command: str = "run heartbeat check",
    notify: bool = True,
    timeout: int = 300,
) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description="test skill",
        location="/fake",
        body="",
        triggers=[
            SkillTrigger(
                command=command,
                schedule=schedule,
                notify=notify,
                timeout=timeout,
            )
        ],
    )


def _make_agent_factory() -> MagicMock:
    agent = AsyncMock()
    agent.run = AsyncMock(return_value="ok")
    factory = MagicMock(return_value=agent)
    return factory


def _make_scheduler(
    skills: list[SkillMetadata] | None = None,
    agent_factory: MagicMock | None = None,
    send_notification: AsyncMock | None = None,
    tick_interval: float = 0.1,
) -> AssistantScheduler:
    mgr = SkillManager()
    mgr._skills = skills if skills is not None else [_make_skill()]
    return AssistantScheduler(
        skill_manager=mgr,
        agent_factory=agent_factory or _make_agent_factory(),
        send_notification=send_notification or AsyncMock(),
        tick_interval=tick_interval,
    )


@pytest.mark.asyncio
async def test_start_stop_lifecycle():
    scheduler = _make_scheduler()
    assert not scheduler.running
    await scheduler.start()
    assert scheduler.running
    await scheduler.stop()
    assert not scheduler.running


@pytest.mark.asyncio
async def test_start_idempotent():
    scheduler = _make_scheduler()
    await scheduler.start()
    task1 = scheduler._task
    await scheduler.start()
    assert scheduler._task is task1
    await scheduler.stop()


@pytest.mark.asyncio
async def test_stop_when_not_started():
    scheduler = _make_scheduler()
    await scheduler.stop()
    assert not scheduler.running


@pytest.mark.asyncio
async def test_initial_last_run_set_to_now():
    skill = _make_skill()
    scheduler = _make_scheduler(skills=[skill])
    before = datetime.now(UTC)
    await scheduler.start()
    after = datetime.now(UTC)
    key = "heartbeat:0"
    assert key in scheduler._last_run
    assert before <= scheduler._last_run[key] <= after
    await scheduler.stop()


@pytest.mark.asyncio
async def test_trigger_not_due():
    """Trigger should not fire right after start (last_run = now)."""
    factory = _make_agent_factory()
    scheduler = _make_scheduler(agent_factory=factory)
    await scheduler.start()
    await scheduler._tick()
    factory.assert_not_called()
    await scheduler.stop()


@pytest.mark.asyncio
async def test_trigger_due():
    """Trigger should fire when last_run is far enough in the past."""
    factory = _make_agent_factory()
    notification = AsyncMock()
    scheduler = _make_scheduler(agent_factory=factory, send_notification=notification)
    await scheduler.start()
    # Push last_run back 31 minutes so */30 cron is due
    key = "heartbeat:0"
    scheduler._last_run[key] = datetime.now(UTC) - timedelta(minutes=31)
    await scheduler._tick()
    factory.assert_called_once_with("scheduler-heartbeat")
    factory.return_value.run.assert_awaited_once()
    notification.assert_awaited_once()
    assert "heartbeat" in notification.call_args[0][0]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_trigger_notify_false():
    """When notify=False, no notification should be sent."""
    factory = _make_agent_factory()
    notification = AsyncMock()
    skill = _make_skill(notify=False)
    scheduler = _make_scheduler(skills=[skill], agent_factory=factory, send_notification=notification)
    await scheduler.start()
    scheduler._last_run["heartbeat:0"] = datetime.now(UTC) - timedelta(minutes=31)
    await scheduler._tick()
    factory.assert_called_once()
    notification.assert_not_awaited()
    await scheduler.stop()


@pytest.mark.asyncio
async def test_trigger_timeout():
    """A trigger that exceeds timeout should log warning and notify."""
    factory = _make_agent_factory()

    async def slow_run(**kwargs):
        await asyncio.sleep(10)

    factory.return_value.run = AsyncMock(side_effect=slow_run)
    notification = AsyncMock()
    skill = _make_skill(timeout=1)
    scheduler = _make_scheduler(skills=[skill], agent_factory=factory, send_notification=notification)
    await scheduler.start()
    scheduler._last_run["heartbeat:0"] = datetime.now(UTC) - timedelta(minutes=31)
    await scheduler._tick()
    notification.assert_awaited_once()
    assert "timed out" in notification.call_args[0][0]
    await scheduler.stop()


@pytest.mark.asyncio
async def test_trigger_execution_error():
    """If agent.run raises, scheduler should continue and notify."""
    factory = _make_agent_factory()
    factory.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
    notification = AsyncMock()
    scheduler = _make_scheduler(agent_factory=factory, send_notification=notification)
    await scheduler.start()
    scheduler._last_run["heartbeat:0"] = datetime.now(UTC) - timedelta(minutes=31)
    await scheduler._tick()
    notification.assert_awaited_once()
    assert "failed" in notification.call_args[0][0]
    # Scheduler should still be running
    assert scheduler.running
    await scheduler.stop()


@pytest.mark.asyncio
async def test_invalid_cron_expression():
    """Invalid cron expression should be skipped without crashing."""
    skill = _make_skill(schedule="not a cron")
    factory = _make_agent_factory()
    scheduler = _make_scheduler(skills=[skill], agent_factory=factory)
    await scheduler.start()
    scheduler._last_run["heartbeat:0"] = datetime.now(UTC) - timedelta(minutes=31)
    await scheduler._tick()
    factory.assert_not_called()
    assert scheduler.running
    await scheduler.stop()


@pytest.mark.asyncio
async def test_hot_reload_picks_up_new_skills():
    """New skills added to the manager should be picked up on next tick."""
    mgr = SkillManager()
    mgr._skills = []
    factory = _make_agent_factory()
    scheduler = AssistantScheduler(
        skill_manager=mgr,
        agent_factory=factory,
        send_notification=AsyncMock(),
        tick_interval=0.1,
    )
    await scheduler.start()
    # No triggers initially
    await scheduler._tick()
    factory.assert_not_called()

    # Add a skill dynamically
    new_skill = _make_skill(name="new-skill")
    mgr._skills.append(new_skill)

    # First tick initializes last_run for the new skill
    await scheduler._tick()
    assert "new-skill:0" in scheduler._last_run
    factory.assert_not_called()

    # Push back last_run and tick again — should fire
    scheduler._last_run["new-skill:0"] = datetime.now(UTC) - timedelta(minutes=31)
    await scheduler._tick()
    factory.assert_called_once_with("scheduler-new-skill")
    await scheduler.stop()


@pytest.mark.asyncio
async def test_no_schedule_triggers_skipped():
    """Skills with only event triggers (no schedule) should be skipped."""
    skill = SkillMetadata(
        name="event-only",
        description="event trigger",
        location="/fake",
        body="",
        triggers=[
            SkillTrigger(command="do thing", event="github.push"),
        ],
    )
    factory = _make_agent_factory()
    scheduler = _make_scheduler(skills=[skill], agent_factory=factory)
    await scheduler.start()
    # No schedule key should be initialized
    assert len(scheduler._last_run) == 0
    await scheduler._tick()
    factory.assert_not_called()
    await scheduler.stop()


@pytest.mark.asyncio
async def test_last_run_updated_after_execution():
    """After execution, last_run should be updated to ~now."""
    factory = _make_agent_factory()
    scheduler = _make_scheduler(agent_factory=factory)
    await scheduler.start()
    key = "heartbeat:0"
    old_time = datetime.now(UTC) - timedelta(minutes=31)
    scheduler._last_run[key] = old_time
    before = datetime.now(UTC)
    await scheduler._tick()
    after = datetime.now(UTC)
    assert scheduler._last_run[key] >= before
    assert scheduler._last_run[key] <= after
    await scheduler.stop()


@pytest.mark.asyncio
async def test_work_dir_from_trigger():
    """Trigger-level work_dir should override the scheduler default."""
    factory = _make_agent_factory()
    skill = SkillMetadata(
        name="custom-dir",
        description="test",
        location="/fake",
        body="",
        triggers=[
            SkillTrigger(
                command="check",
                schedule="*/30 * * * *",
                work_dir="/custom/path",
            ),
        ],
    )
    scheduler = _make_scheduler(skills=[skill], agent_factory=factory)
    await scheduler.start()
    scheduler._last_run["custom-dir:0"] = datetime.now(UTC) - timedelta(minutes=31)
    await scheduler._tick()
    call_kwargs = factory.return_value.run.call_args[1]
    from pathlib import Path

    assert call_kwargs["work_dir"] == Path("/custom/path")
    await scheduler.stop()
