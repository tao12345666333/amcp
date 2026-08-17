"""Acceptance tests for the single-owner session runtime."""

import asyncio

import pytest

from ankaloop.message_queue import MessagePriority
from ankaloop.runtime import (
    RuntimeClosedError,
    SessionRuntime,
    SessionRuntimeStatus,
    TurnCancelledError,
    TurnStatus,
)
from ankaloop.server.turn_stream import turn_frames


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


@pytest.mark.asyncio
async def test_turn_output_subscriptions_are_request_scoped():
    release = asyncio.Event()

    async def process(request):
        await release.wait()
        return request.prompt

    runtime = SessionRuntime("streams", process)
    first = await runtime.submit("first")
    second = await runtime.submit("second")
    first_events = first.subscribe()
    second_events = second.subscribe()

    runtime.publish_turn_event(first.id, "message.chunk", {"content": "one"})
    runtime.publish_turn_event(second.id, "message.chunk", {"content": "two"})

    assert (await first_events.get()).data["content"] == "one"
    assert (await second_events.get()).data["content"] == "two"
    assert first_events.empty()
    assert second_events.empty()

    first.unsubscribe(first_events)
    second.unsubscribe(second_events)
    release.set()
    await asyncio.gather(first.wait(), second.wait())


@pytest.mark.asyncio
async def test_slow_turn_subscriber_is_failed_without_cancelling_turn():
    release = asyncio.Event()

    async def process(request):
        await release.wait()
        return request.prompt

    runtime = SessionRuntime("slow-stream", process)
    handle = await runtime.submit("result")
    events = handle.subscribe(max_queue_size=1)

    runtime.publish_turn_event(handle.id, "message.chunk", {"content": "first"})
    runtime.publish_turn_event(handle.id, "message.chunk", {"content": "second"})

    overflow = await events.get()
    assert overflow.type == "stream.overflow"
    assert events not in handle._stream_subscribers
    release.set()
    assert await handle.wait() == "result"


@pytest.mark.asyncio
async def test_closing_turn_relay_unsubscribes_without_cancelling_turn():
    release = asyncio.Event()

    async def process(request):
        await release.wait()
        return request.prompt

    runtime = SessionRuntime("disconnect", process)
    handle = await runtime.submit("result")
    frames = turn_frames(handle, "disconnect")

    assert (await anext(frames))["type"] == "start"
    assert len(handle._stream_subscribers) == 1
    await frames.aclose()
    assert not handle._stream_subscribers

    release.set()
    assert await handle.wait() == "result"
