"""Server-Sent Events (SSE) handler for AMCP Server.

Provides one-way real-time event streaming for:
- Session status changes
- Tool execution events
- Message streaming
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .models import EventType, ServerEvent
from .session_manager import SessionNotFoundError, get_session_manager

router = APIRouter()


class EventEmitter:
    """Manages SSE event subscriptions."""

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._global_subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str | None = None) -> asyncio.Queue:
        """Subscribe to events.

        Args:
            session_id: Optional session ID to filter events.

        Returns:
            Queue that will receive events.
        """
        queue: asyncio.Queue = asyncio.Queue()

        async with self._lock:
            if session_id:
                if session_id not in self._subscribers:
                    self._subscribers[session_id] = []
                self._subscribers[session_id].append(queue)
            else:
                self._global_subscribers.append(queue)

        return queue

    async def unsubscribe(self, queue: asyncio.Queue, session_id: str | None = None) -> None:
        """Unsubscribe from events.

        Args:
            queue: The queue to unsubscribe.
            session_id: Optional session ID.
        """
        async with self._lock:
            if session_id and session_id in self._subscribers:
                if queue in self._subscribers[session_id]:
                    self._subscribers[session_id].remove(queue)
            elif queue in self._global_subscribers:
                self._global_subscribers.remove(queue)

    async def emit(self, event: ServerEvent) -> None:
        """Emit an event to subscribers.

        Args:
            event: The event to emit.
        """
        event_dict = event.model_dump()
        event_dict["timestamp"] = event.timestamp.isoformat()

        # Send to session-specific subscribers
        if event.session_id and event.session_id in self._subscribers:
            for queue in self._subscribers[event.session_id]:
                await queue.put(event_dict)

        # Send to global subscribers
        for queue in self._global_subscribers:
            await queue.put(event_dict)

    async def emit_raw(self, event_type: str, session_id: str | None, payload: dict[str, Any]) -> None:
        """Emit a raw event.

        Args:
            event_type: Type of event.
            session_id: Optional session ID.
            payload: Event payload.
        """
        event = ServerEvent(
            type=EventType(event_type) if event_type in [e.value for e in EventType] else EventType.CONNECTED,
            session_id=session_id,
            payload=payload,
        )
        await self.emit(event)


# Global event emitter
event_emitter = EventEmitter()


async def event_generator(
    queue: asyncio.Queue,
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Generate SSE events.

    Args:
        queue: Queue to receive events from.
        session_id: Optional session ID for this subscription.

    Yields:
        SSE formatted event strings.
    """
    try:
        # Send connected event
        connected_event: dict[str, Any] = {
            "type": EventType.CONNECTED.value,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "payload": {},
        }
        yield f"event: connected\ndata: {json.dumps(connected_event)}\n\n"

        # Periodically send heartbeats and check for events
        while True:
            try:
                # Wait for event with timeout
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"event: {event.get('type', 'message')}\ndata: {json.dumps(event)}\n\n"

            except TimeoutError:
                # Send heartbeat
                heartbeat = {
                    "type": EventType.HEARTBEAT.value,
                    "timestamp": datetime.now().isoformat(),
                }
                yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n"

    except asyncio.CancelledError:
        pass


@router.get("/events")
async def global_events(request: Request) -> StreamingResponse:
    """Subscribe to global events stream.

    Receives all events from the server including:
    - Session created/deleted
    - Agent status changes

    Returns an SSE stream.
    """
    queue = await event_emitter.subscribe()

    async def cleanup_generator():
        try:
            async for event in event_generator(queue, None):
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                yield event
        finally:
            await event_emitter.unsubscribe(queue, None)

    return StreamingResponse(
        cleanup_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions/{session_id}/events")
async def session_events(request: Request, session_id: str) -> StreamingResponse:
    """Subscribe to events for a specific session.

    Receives events related to a specific session:
    - Message chunks (streaming)
    - Tool calls and results
    - Status changes

    Returns an SSE stream.
    """
    # Verify session exists
    session_manager = get_session_manager()
    try:
        await session_manager.get_session(session_id)
    except SessionNotFoundError:

        async def error_generator():
            error = {
                "type": "error",
                "error": f"Session not found: {session_id}",
                "code": "SESSION_NOT_FOUND",
            }
            yield f"event: error\ndata: {json.dumps(error)}\n\n"

        return StreamingResponse(
            error_generator(),
            media_type="text/event-stream",
        )

    queue = await event_emitter.subscribe(session_id)

    async def cleanup_generator():
        try:
            async for event in event_generator(queue, session_id):
                if await request.is_disconnected():
                    break
                yield event
        finally:
            await event_emitter.unsubscribe(queue, session_id)

    return StreamingResponse(
        cleanup_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Session-ID": session_id,
        },
    )


def get_event_emitter() -> EventEmitter:
    """Get the global event emitter."""
    return event_emitter


async def emit_event(event_type: str, session_id: str | None = None, **payload) -> None:
    """Convenience function to emit an event.

    Args:
        event_type: Type of event from EventType enum.
        session_id: Optional session ID.
        **payload: Event payload data.
    """
    await event_emitter.emit_raw(event_type, session_id, payload)
