"""Server-side effects for shared AMCP interaction routing."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from ..interaction import InteractionResult, route_interaction
from .models import Session
from .session_manager import ManagedSession, SessionManager, SessionNotFoundError


def format_session_list(sessions: list[Session], current_session_id: str | None = None) -> str:
    """Format sessions consistently for chat surfaces."""
    if not sessions:
        return "Sessions:\n(none)"
    lines = ["Sessions:"]
    for session in sessions:
        marker = "*" if session.id == current_session_id else "-"
        lines.append(f"{marker} {session.id} ({session.status.value})")
    return "\n".join(lines)


def format_session_info(session: ManagedSession) -> str:
    """Format one session summary."""
    summary = session.agent.get_conversation_summary()
    return "\n".join(
        [
            "Session Info:",
            f"Session ID: {session.id}",
            f"Agent: {session.agent_name}",
            f"Status: {session.status.value}",
            f"Messages: {session.message_count}",
            f"History messages: {summary.get('message_count', 0)}",
            f"Queued: {session.agent.queued_count()}",
        ]
    )


async def apply_interaction_result(
    session_manager: SessionManager,
    session_id: str,
    result: InteractionResult,
) -> AsyncGenerator[dict, None]:
    """Apply a routed interaction result and yield protocol-neutral events."""
    if result.action == "message":
        yield {
            "type": "chunk",
            "content": result.content,
            "message_type": result.message_type,
        }
        return

    if result.action == "new_session":
        current = await session_manager.get_session(session_id)
        new_session = await session_manager.create_session(
            cwd=current.cwd,
            agent_name=current.agent_name,
        )
        yield {
            "type": "session_created",
            "session_id": new_session.id,
            "previous_session_id": session_id,
            "content": f"Created session: {new_session.id}",
        }
        return

    if result.action == "session_list":
        sessions = await session_manager.list_sessions()
        yield {"type": "chunk", "content": format_session_list(sessions, session_id)}
        return

    if result.action == "session_switch":
        target_id = result.session_id or ""
        try:
            await session_manager.get_session(target_id)
        except SessionNotFoundError:
            yield {
                "type": "chunk",
                "content": f"Unknown session: {target_id}",
                "message_type": "error",
            }
            return
        yield {
            "type": "session_switched",
            "session_id": target_id,
            "previous_session_id": session_id,
            "content": f"Switched to session: {target_id}",
        }
        return

    if result.action == "clear":
        session = await session_manager.get_session(session_id)
        session.agent.clear_conversation_history()
        yield {"type": "chunk", "content": f"Conversation history cleared for session: {session_id}"}
        return

    if result.action == "info":
        session = await session_manager.get_session(session_id)
        yield {"type": "chunk", "content": format_session_info(session)}
        return

    if result.action == "cancel":
        await session_manager.cancel_session(session_id)
        yield {"type": "chunk", "content": f"Cancel request sent for session: {session_id}"}
        return

    if result.action == "exit":
        yield {"type": "chunk", "content": "Exit is handled by the connected client."}


async def route_server_interaction(
    session_manager: SessionManager,
    session_id: str,
    content: str,
) -> tuple[InteractionResult, ManagedSession]:
    """Route one server prompt and return the current session."""
    session = await session_manager.get_session(session_id)
    result = route_interaction(
        content,
        work_dir=Path(session.cwd),
        project_root=Path(session.cwd),
    )
    return result, session
