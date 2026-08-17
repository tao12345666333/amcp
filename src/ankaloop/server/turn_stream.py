"""Transport-neutral streaming frames for runtime-owned turns."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from ..llm import ProviderError
from ..runtime import TurnHandle, TurnStatus, TurnStreamEvent


def _event_frame(event: TurnStreamEvent, handle: TurnHandle) -> dict[str, Any] | None:
    """Convert an internal turn event to the public streaming schema."""
    base = {"turn_id": event.turn_id}
    if event.type == "message.chunk":
        return {"type": "chunk", **base, "content": event.data.get("content", "")}
    if event.type.startswith("tool.call_"):
        return {
            "type": "tool",
            **base,
            "event": event.type.removeprefix("tool."),
            **{key: value for key, value in event.data.items() if key not in {"session_id", "turn_id"}},
        }
    if event.type == "turn.completed":
        return {"type": "complete", **base, "status": "completed"}
    if event.type in {"turn.failed", "turn.cancelled"}:
        cancelled = event.type == "turn.cancelled"
        error = handle.outcome.error if handle.outcome is not None else None
        provider = error if isinstance(error, ProviderError) else None
        return {
            "type": "error",
            **base,
            "error": event.data.get("error") or ("Turn cancelled" if cancelled else "Turn failed"),
            "code": (
                "TURN_CANCELLED"
                if cancelled
                else f"PROVIDER_{provider.kind.value.upper()}"
                if provider
                else "AGENT_ERROR"
            ),
            "retryable": provider.retryable if provider else False,
        }
    if event.type == "stream.overflow":
        return {
            "type": "error",
            **base,
            "error": event.data["error"],
            "code": "SLOW_CONSUMER",
            "retryable": True,
        }
    return None


async def turn_frames(handle: TurnHandle, session_id: str) -> AsyncGenerator[dict[str, Any], None]:
    """Relay one turn without making the transport own its execution lifecycle."""
    queue = handle.subscribe()
    sent_chunk = False
    try:
        yield {
            "type": "start",
            "turn_id": handle.id,
            "session_id": session_id,
            "status": handle.status.value,
        }
        while True:
            if handle.done and queue.empty():
                outcome = handle.outcome
                if outcome is not None and outcome.value:
                    yield {"type": "chunk", "turn_id": handle.id, "content": outcome.value}
                if handle.status == TurnStatus.CANCELLED:
                    event_type = "turn.cancelled"
                elif handle.status == TurnStatus.COMPLETED:
                    event_type = "turn.completed"
                else:
                    event_type = "turn.failed"
                frame = _event_frame(TurnStreamEvent(handle.id, event_type), handle)
                assert frame is not None
                yield frame
                return
            event = await queue.get()
            frame = _event_frame(event, handle)
            if frame is None:
                continue
            if frame["type"] == "complete" and not sent_chunk:
                outcome = handle.outcome
                if outcome is not None and outcome.value:
                    yield {"type": "chunk", "turn_id": handle.id, "content": outcome.value}
            if frame["type"] == "chunk":
                sent_chunk = True
            yield frame
            if frame["type"] in {"complete", "error"}:
                return
    finally:
        handle.unsubscribe(queue)
