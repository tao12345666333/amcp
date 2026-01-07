"""Session management endpoints."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..models import (
    CancelRequest,
    CreateSessionRequest,
    PromptRequest,
    PromptResponse,
    Session,
    SessionListResponse,
)
from ..session_manager import (
    MaxSessionsReachedError,
    SessionNotFoundError,
    get_session_manager,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=Session)
async def create_session(request: CreateSessionRequest | None = None) -> Session:
    """Create a new session.

    Creates a new agent session with optional working directory
    and agent specification.
    """
    session_manager = get_session_manager()

    try:
        req = request or CreateSessionRequest()
        managed_session = await session_manager.create_session(
            cwd=req.cwd,
            agent_name=req.agent_name,
        )
        return managed_session.to_session()
    except MaxSessionsReachedError as e:
        raise HTTPException(
            status_code=429,
            detail={"error": str(e), "code": "MAX_SESSIONS_REACHED"},
        )


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
        )


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
        )


@router.post("/{session_id}/prompt", response_model=PromptResponse)
async def send_prompt(session_id: str, request: PromptRequest) -> PromptResponse:
    """Send a prompt to a session.

    For streaming responses, use the /sessions/{id}/prompt/stream endpoint.
    This endpoint queues the message and returns immediately.
    """
    session_manager = get_session_manager()

    try:
        session = await session_manager.get_session(session_id)
        message_id = f"msg-{uuid.uuid4().hex[:12]}"

        # Check if busy
        if session.agent.is_busy():
            # Queue the message
            return PromptResponse(
                session_id=session_id,
                message_id=message_id,
                status="queued",
                position=session.agent.queued_count() + 1,
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
        )


@router.post("/{session_id}/prompt/stream")
async def send_prompt_stream(session_id: str, request: PromptRequest) -> StreamingResponse:
    """Send a prompt and stream the response.

    Returns a streaming response with chunks from the agent.
    Each chunk is a JSON object followed by a newline.
    """
    session_manager = get_session_manager()

    try:
        await session_manager.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Session not found: {session_id}", "code": "SESSION_NOT_FOUND"},
        )

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
        )


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
        )


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
        )
