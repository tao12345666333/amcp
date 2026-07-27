"""Acceptance tests for the single-owner session runtime."""

import asyncio

import pytest

from amcp.message_queue import MessagePriority
from amcp.runtime import (
    RuntimeClosedError,
    SessionRuntime,
    SessionRuntimeStatus,
    TurnCancelledError,
    TurnStatus,
)


@pytest.mark.asyncio
async def test_same_session_turns_are_serial_and_keep_independent_results():
    order = []

    async def process(request):
        order.append(("start", request.prompt))
        await asyncio.sleep(0.01)
        if request.prompt == "fail":
            raise ValueError("expected failure")
        order.append(("end", request.prompt))
        return request.prompt.upper()

    runtime = SessionRuntime("serial", process)
    first = await runtime.submit("first")
    failed = await runtime.submit("fail")
    last = await runtime.submit("last")

    assert await first.wait() == "FIRST"
    with pytest.raises(ValueError, match="expected failure"):
        await failed.wait()
    assert await last.wait() == "LAST"
    assert order == [
        ("start", "first"),
        ("end", "first"),
        ("start", "fail"),
        ("start", "last"),
        ("end", "last"),
    ]
    assert [first.status, failed.status, last.status] == [
        TurnStatus.COMPLETED,
        TurnStatus.FAILED,
        TurnStatus.COMPLETED,
    ]


@pytest.mark.asyncio
async def test_different_sessions_run_concurrently():
    started = asyncio.Event()
    release = asyncio.Event()
    count = 0

    async def process(request):
        nonlocal count
        count += 1
        if count == 2:
            started.set()
        await release.wait()
        return request.prompt

    first_runtime = SessionRuntime("one", process)
    second_runtime = SessionRuntime("two", process)
    first = await first_runtime.submit("first")
    second = await second_runtime.submit("second")

    await asyncio.wait_for(started.wait(), timeout=1)
    release.set()
    assert await asyncio.gather(first.wait(), second.wait()) == ["first", "second"]


@pytest.mark.asyncio
async def test_cancel_active_turn_does_not_complete_it_or_drop_followup():
    started = asyncio.Event()

    async def process(request):
        if request.prompt == "slow":
            started.set()
            await asyncio.sleep(60)
        return request.prompt

    runtime = SessionRuntime("cancel", process)
    slow = await runtime.submit("slow")
    followup = await runtime.submit("followup")
    await started.wait()

    assert await runtime.cancel_active() is True
    with pytest.raises(TurnCancelledError):
        await slow.wait()
    assert await followup.wait() == "followup"
    assert slow.status == TurnStatus.CANCELLED


@pytest.mark.asyncio
async def test_priority_orders_queued_turns_after_active_turn():
    release = asyncio.Event()

    async def process(request):
        if request.prompt == "active":
            await release.wait()
        return request.prompt

    runtime = SessionRuntime("priority", process)
    active = await runtime.submit("active")
    await asyncio.sleep(0)
    low = await runtime.submit("low", priority=MessagePriority.LOW)
    urgent = await runtime.submit("urgent", priority=MessagePriority.URGENT)
    release.set()

    assert await active.wait() == "active"
    assert await urgent.wait() == "urgent"
    assert await low.wait() == "low"


@pytest.mark.asyncio
async def test_clear_queue_cancels_each_queued_handle():
    started = asyncio.Event()

    async def process(request):
        started.set()
        await asyncio.sleep(60)
        return request.prompt

    runtime = SessionRuntime("clear", process)
    active = await runtime.submit("active")
    await started.wait()
    queued = await runtime.submit("queued")

    assert await runtime.clear_queue() == 1
    with pytest.raises(TurnCancelledError):
        await queued.wait()
    await runtime.cancel_active()
    with pytest.raises(TurnCancelledError):
        await active.wait()


@pytest.mark.asyncio
async def test_cancel_all_reports_active_and_queued_work():
    started = asyncio.Event()

    async def process(request):
        started.set()
        await asyncio.sleep(60)
        return request.prompt

    runtime = SessionRuntime("cancel-all", process)
    active = await runtime.submit("active")
    await started.wait()
    queued = await runtime.submit("queued")

    result = await runtime.cancel_all()

    assert result.active_cancelled is True
    assert result.queued_cancelled == 1
    with pytest.raises(TurnCancelledError):
        await active.wait()
    with pytest.raises(TurnCancelledError):
        await queued.wait()


@pytest.mark.asyncio
async def test_close_cancels_work_is_idempotent_and_rejects_submit():
    started = asyncio.Event()

    async def process(request):
        started.set()
        await asyncio.sleep(60)
        return request.prompt

    runtime = SessionRuntime("close", process)
    active = await runtime.submit("active")
    await started.wait()
    queued = await runtime.submit("queued")

    await runtime.close()
    await runtime.close()

    assert runtime.status == SessionRuntimeStatus.CLOSED
    assert runtime.is_closed is True
    with pytest.raises(TurnCancelledError):
        await active.wait()
    with pytest.raises(TurnCancelledError):
        await queued.wait()
    with pytest.raises(RuntimeClosedError):
        await runtime.submit("late")


@pytest.mark.asyncio
async def test_terminal_handle_retention_is_bounded():
    async def process(request):
        return request.prompt

    runtime = SessionRuntime("retention", process, terminal_handle_retention=2)
    handles = [await runtime.submit(str(index)) for index in range(5)]
    await asyncio.gather(*(handle.wait() for handle in handles))

    assert runtime.get_turn(handles[0].id) is None
    assert runtime.get_turn(handles[1].id) is None
    assert runtime.get_turn(handles[2].id) is None
    assert runtime.get_turn(handles[3].id) is handles[3]
    assert runtime.get_turn(handles[4].id) is handles[4]
