"""Session management endpoints."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncGenerator, Coroutine
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..models import (
    CancelRequest,
    ConflictStrategy,
    CreateSessionRequest,
    PromptRequest,
    PromptResponse,
    Session,
    SessionListResponse,
    SessionStatus,
)
from ..session_manager import (
    MaxSessionsReachedError,
    SessionNotFoundError,
    get_session_manager,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _safe_emit(coro: Coroutine[Any, Any, None]) -> None:
    """Safely emit an event, suppressing any exceptions."""
    with contextlib.suppress(Exception):
        await coro


@router.post("", response_model=Session)
async def create_session(request: CreateSessionRequest | None = None) -> Session:
    """Create a new session.

    Creates a new agent session with optional working directory
    and agent specification.
    """
    session_manager = get_session_manager()

    try:
        req = request or CreateSessionRequest(cwd=None, agent_name=None)
        managed_session = await session_manager.create_session(
            cwd=req.cwd,
            agent_name=req.agent_name,
        )
        return managed_session.to_session()
    except MaxSessionsReachedError as e:
        raise HTTPException(
            status_code=429,
            detail={"error": str(e), "code": "MAX_SESSIONS_REACHED"},
        ) from None


@router.get("", response_model=SessionListResponse)
async def list_sessions() -> SessionListResponse:
    """List all active sessions."""
    session_manager = get_session_manager()
    sessions = await session_manager.list_sessions()
    return SessionListResponse(sessions=sessions, total=len(sessions))


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: str) -> Session:
    """Get session details by ID."""
    session_manager = get_session_manager()

    try:
        managed_session = await session_manager.get_session(session_id)
        return managed_session.to_session()
    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Session not found: {session_id}", "code": "SESSION_NOT_FOUND"},
        ) from None


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Delete a session."""
    session_manager = get_session_manager()

    try:
        await session_manager.delete_session(session_id)
        return {"status": "deleted", "session_id": session_id}
    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Session not found: {session_id}", "code": "SESSION_NOT_FOUND"},
        ) from None


@router.post("/{session_id}/prompt", response_model=PromptResponse)
async def send_prompt(session_id: str, request: PromptRequest) -> PromptResponse:
    """Send a prompt to a session.

    For streaming responses, use the /sessions/{id}/prompt/stream endpoint.
    This endpoint queues the message and returns immediately.

    The `conflict_strategy` parameter controls behavior when the session is busy:
    - `queue`: Add the prompt to the queue (default)
    - `reject`: Reject the prompt with an error
    """
    session_manager = get_session_manager()

    try:
        session = await session_manager.get_session(session_id)
        message_id = f"msg-{uuid.uuid4().hex[:12]}"

        # Get event bridge for collaboration events
        from ..event_bridge import get_event_bridge

        bridge = get_event_bridge()

        # Emit collaboration event: notify other clients about incoming prompt
        await _safe_emit(
            bridge.emit_prompt_received(
                session_id=session_id,
                content=request.content,
                priority=request.priority.value,
            )
        )

        # Check if busy and handle based on conflict strategy
        is_busy = session.status == SessionStatus.BUSY or session.agent.is_busy()
        if is_busy and request.conflict_strategy == ConflictStrategy.REJECT:
            # Notify about rejection
            await _safe_emit(
                bridge.emit_prompt_rejected(
                    session_id=session_id,
                    reason="Session is busy",
                    conflict_strategy="reject",
                )
            )

            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Session is busy, prompt rejected",
                    "code": "SESSION_BUSY",
                    "session_id": session_id,
                },
            )

        if is_busy:
            # Default: queue the message
            position = session.agent.queued_count() + 1

            # Notify about queuing
            await _safe_emit(
                bridge.emit_prompt_queued(
                    session_id=session_id,
                    message_id=message_id,
                    position=position,
                )
            )

            return PromptResponse(
                session_id=session_id,
                message_id=message_id,
                status="queued",
                position=position,
            )

        # Notify that processing started
        await _safe_emit(
            bridge.emit_prompt_started(
                session_id=session_id,
                message_id=message_id,
            )
        )

        return PromptResponse(
            session_id=session_id,
            message_id=message_id,
            status="streaming" if request.stream else "processing",
        )

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Session not found: {session_id}", "code": "SESSION_NOT_FOUND"},
        ) from None


@router.post("/{session_id}/prompt/stream")
async def send_prompt_stream(session_id: str, request: PromptRequest) -> StreamingResponse:
    """Send a prompt and stream the response.

    Returns a streaming response with chunks from the agent.
    Each chunk is a JSON object followed by a newline.

    The `conflict_strategy` parameter controls behavior when the session is busy:
    - `queue`: Wait for the queue (default)
    - `reject`: Reject the prompt with an error
    """
    session_manager = get_session_manager()

    try:
        session = await session_manager.get_session(session_id)

        # Get event bridge for collaboration events
        from ..event_bridge import get_event_bridge

        bridge = get_event_bridge()

        # Emit collaboration event: notify other clients about incoming prompt
        await _safe_emit(
            bridge.emit_prompt_received(
                session_id=session_id,
                content=request.content,
                priority=request.priority.value,
            )
        )

        # Check for conflict and handle based on strategy
        is_busy = session.status == SessionStatus.BUSY or session.agent.is_busy()
        if is_busy and request.conflict_strategy == ConflictStrategy.REJECT:
            # Notify about rejection
            await _safe_emit(
                bridge.emit_prompt_rejected(
                    session_id=session_id,
                    reason="Session is busy",
                    conflict_strategy="reject",
                )
            )

            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Session is busy, prompt rejected",
                    "code": "SESSION_BUSY",
                    "session_id": session_id,
                },
            )
        # For QUEUE strategy, continue - the agent will queue internally

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Session not found: {session_id}", "code": "SESSION_NOT_FOUND"},
        ) from None

    async def generate() -> AsyncGenerator[str, None]:
        import json

        message_id = f"msg-{uuid.uuid4().hex[:12]}"

        # Send start event
        yield (
            json.dumps(
                {
                    "type": "start",
                    "message_id": message_id,
                    "session_id": session_id,
                }
            )
            + "\n"
        )

        try:
            async for chunk in session_manager.prompt_session(
                session_id=session_id,
                content=request.content,
                stream=True,
                priority=request.priority.value,
            ):
                if isinstance(chunk, str):
                    yield (
                        json.dumps(
                            {
                                "type": "chunk",
                                "content": chunk,
                            }
                        )
                        + "\n"
                    )
                elif hasattr(chunk, "content"):
                    yield (
                        json.dumps(
                            {
                                "type": "chunk",
                                "content": chunk.content,
                            }
                        )
                        + "\n"
                    )

            # Send complete event
            yield (
                json.dumps(
                    {
                        "type": "complete",
                        "message_id": message_id,
                    }
                )
                + "\n"
            )

        except Exception as e:
            yield (
                json.dumps(
                    {
                        "type": "error",
                        "error": str(e),
                    }
                )
                + "\n"
            )

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-ID": session_id,
        },
    )


@router.post("/{session_id}/cancel")
async def cancel_session(session_id: str, request: CancelRequest | None = None) -> dict:
    """Cancel the current operation in a session."""
    session_manager = get_session_manager()

    try:
        req = request or CancelRequest()
        await session_manager.cancel_session(session_id, force=req.force)
        return {"status": "cancelled", "session_id": session_id}
    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Session not found: {session_id}", "code": "SESSION_NOT_FOUND"},
        ) from None


@router.get("/{session_id}/history")
async def get_session_history(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Get conversation history for a session."""
    session_manager = get_session_manager()

    try:
        session = await session_manager.get_session(session_id)
        history = session.agent.conversation_history[-limit:]

        return {
            "session_id": session_id,
            "messages": history,
            "total": len(session.agent.conversation_history),
            "returned": len(history),
        }
    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Session not found: {session_id}", "code": "SESSION_NOT_FOUND"},
        ) from None


@router.delete("/{session_id}/history")
async def clear_session_history(session_id: str) -> dict:
    """Clear conversation history for a session."""
    session_manager = get_session_manager()

    try:
        session = await session_manager.get_session(session_id)
        session.agent.clear_conversation_history()

        return {"status": "cleared", "session_id": session_id}
    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Session not found: {session_id}", "code": "SESSION_NOT_FOUND"},
        ) from None
