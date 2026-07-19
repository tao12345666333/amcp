from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from amcp.telegram.scheduler import (
    SCHEDULE_BLUEPRINTS,
    TelegramPromptScheduler,
    TelegramScheduleStore,
)
from amcp.telegram.tools import TelegramScheduleTool


class _ScheduledAgent:
    def __init__(self, result: str) -> None:
        self.result = result
        self.execution_context: dict[str, str] = {}
        self.inputs: list[str] = []

    async def run(self, **kwargs):
        self.inputs.append(kwargs["user_input"])
        return self.result


def test_schedule_store_persists_jobs(tmp_path):
    now = datetime(2026, 7, 19, 8, 0).astimezone()
    path = tmp_path / "telegram_schedules.json"
    store = TelegramScheduleStore(path, now_factory=lambda: now)

    job = store.create_job(chat_id=123, schedule="0 8 * * *", prompt="send HN", name="hn")
    reloaded = TelegramScheduleStore(path).list_jobs(123)

    assert reloaded == [job]
    assert reloaded[0].name == "hn"
    assert reloaded[0].last_run_at == now.isoformat()


def test_schedule_store_creates_blueprint(tmp_path):
    store = TelegramScheduleStore(tmp_path / "schedules.json")

    job = store.create_blueprint_job(
        chat_id=123,
        blueprint="hackernews_daily",
        schedule="0 8 * * *",
    )

    assert job.blueprint == "hackernews_daily"
    assert job.prompt == SCHEDULE_BLUEPRINTS["hackernews_daily"].prompt


@pytest.mark.asyncio
async def test_prompt_scheduler_runs_due_job_and_sends_result(tmp_path):
    created = datetime(2026, 7, 19, 8, 0).astimezone()
    now = created + timedelta(minutes=31)
    store = TelegramScheduleStore(tmp_path / "schedules.json", now_factory=lambda: created)
    job = store.create_job(chat_id=123, schedule="*/30 * * * *", prompt="send digest", name="digest")
    agent = _ScheduledAgent("digest result")
    factory = MagicMock(return_value=agent)
    sent = AsyncMock()

    def bind(chat_id, bound_agent):
        bound_agent.execution_context["telegram_chat_id"] = str(chat_id)

    scheduler = TelegramPromptScheduler(
        store=store,
        agent_factory=factory,
        send_chat=sent,
        bind_agent_context=bind,
        now_factory=lambda: now,
    )

    await scheduler._tick()

    factory.assert_called_once_with(f"telegram-scheduled-{job.id}")
    sent.assert_awaited_once_with(123, "Scheduled task *digest*:\ndigest result")
    assert agent.execution_context["telegram_chat_id"] == "123"
    assert "[Telegram scheduled prompt]" in agent.inputs[0]
    assert "send digest" in agent.inputs[0]
    assert store.list_jobs(123)[0].last_run_at == now.isoformat()


@pytest.mark.asyncio
async def test_prompt_scheduler_suppresses_silent_result(tmp_path):
    created = datetime(2026, 7, 19, 8, 0).astimezone()
    now = created + timedelta(minutes=31)
    store = TelegramScheduleStore(tmp_path / "schedules.json", now_factory=lambda: created)
    store.create_job(chat_id=123, schedule="*/30 * * * *", prompt="heartbeat")
    sent = AsyncMock()
    scheduler = TelegramPromptScheduler(
        store=store,
        agent_factory=MagicMock(return_value=_ScheduledAgent("[SILENT]")),
        send_chat=sent,
        now_factory=lambda: now,
    )

    await scheduler._tick()

    sent.assert_not_awaited()


def test_telegram_schedule_tool_creates_and_lists_blueprint(tmp_path):
    store = TelegramScheduleStore(tmp_path / "schedules.json")
    tool = TelegramScheduleTool(store)

    created = tool.execute(
        action="create_blueprint",
        chat_id="123",
        blueprint="hackernews_daily",
        schedule="0 8 * * *",
    )
    listed = tool.execute(action="list", chat_id="123")

    assert created.success
    assert created.metadata["blueprint"] == "hackernews_daily"
    assert listed.success
    assert created.metadata["job_id"] in listed.content


def test_telegram_schedule_tool_rejects_bad_cron(tmp_path):
    tool = TelegramScheduleTool(TelegramScheduleStore(tmp_path / "schedules.json"))

    result = tool.execute(action="create", chat_id="123", schedule="not cron", prompt="x")

    assert not result.success
    assert "Invalid cron expression" in (result.error or "")
