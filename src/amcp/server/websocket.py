"""WebSocket handler for AMCP Server.

Provides real-time bidirectional communication for:
- Streaming responses
- Tool execution events
- Session status updates
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from .models import EventType
from .session_manager import SessionNotFoundError, get_session_manager

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self):
        # session_id -> list of websockets
        self._connections: dict[str, list[WebSocket]] = {}
        # Global connections (not tied to a session)
        self._global_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str | None = None) -> None:
        """Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket connection.
            session_id: Optional session ID to associate with.
        """
        await websocket.accept()

        async with self._lock:
            if session_id:
                if session_id not in self._connections:
                    self._connections[session_id] = []
                self._connections[session_id].append(websocket)
            else:
                self._global_connections.append(websocket)

        # Send connected event
        await self._send_message(
            websocket,
            {
                "type": "event",
                "payload": {
                    "kind": EventType.CONNECTED.value,
                    "session_id": session_id,
                },
            },
        )

    async def disconnect(self, websocket: WebSocket, session_id: str | None = None) -> None:
        """Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection.
            session_id: Optional session ID.
        """
        async with self._lock:
            if session_id and session_id in self._connections:
                if websocket in self._connections[session_id]:
                    self._connections[session_id].remove(websocket)
                if not self._connections[session_id]:
                    del self._connections[session_id]
            elif websocket in self._global_connections:
                self._global_connections.remove(websocket)

    async def send_to_session(self, session_id: str, message: dict[str, Any]) -> None:
        """Send a message to all connections for a session.

        Args:
            session_id: The session ID.
            message: The message to send.
        """
        connections = self._connections.get(session_id, [])
        for conn in connections:
            await self._send_message(conn, message)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connections.

        Args:
            message: The message to broadcast.
        """
        # Send to global connections
        for conn in self._global_connections:
            await self._send_message(conn, message)

        # Send to all session connections
        for connections in self._connections.values():
            for conn in connections:
                await self._send_message(conn, message)

    async def _send_message(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        """Send a message to a WebSocket.

        Args:
            websocket: The WebSocket connection.
            message: The message to send.
        """
        try:
            # Add timestamp if not present
            if "timestamp" not in message:
                message["timestamp"] = datetime.now().isoformat()
            await websocket.send_json(message)
        except Exception:
            pass  # Connection might be closed

    def get_connection_stats(self) -> dict[str, Any]:
        """Get connection statistics.

        Returns:
            Dictionary with connection counts per session and global.
        """
        session_counts = {session_id: len(connections) for session_id, connections in self._connections.items()}
        return {
            "global_connections": len(self._global_connections),
            "session_connections": session_counts,
            "total_sessions_with_clients": len(self._connections),
            "total_connections": len(self._global_connections) + sum(len(c) for c in self._connections.values()),
        }

    def get_session_connection_count(self, session_id: str) -> int:
        """Get the number of connections for a specific session.

        Args:
            session_id: The session ID.

        Returns:
            Number of WebSocket connections for the session.
        """
        return len(self._connections.get(session_id, []))


# Global connection manager
connection_manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str | None = Query(default=None),
):
    """WebSocket endpoint for real-time communication.

    Query parameters:
        session_id: Optional session ID to bind this connection to.

    Message format:
        {
            "type": "request|response|event|error",
            "id": "message-id",
            "timestamp": "ISO timestamp",
            "payload": { ... }
        }

    Supported request actions:
        - prompt: Send a prompt to a session
        - cancel: Cancel current operation
        - subscribe: Subscribe to session events
        - ping: Keep-alive ping
    """
    await connection_manager.connect(websocket, session_id)

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()

            # Parse message
            msg_id = data.get("id", str(uuid.uuid4()))
            payload = data.get("payload", {})

            # Handle different actions
            action = payload.get("action", "")

            if action == "ping":
                # Respond with pong
                await websocket.send_json(
                    {
                        "type": "response",
                        "id": msg_id,
                        "payload": {"action": "pong"},
                    }
                )

            elif action == "prompt":
                # Handle prompt
                await handle_prompt(websocket, msg_id, payload)

            elif action == "cancel":
                # Handle cancel
                await handle_cancel(websocket, msg_id, payload)

            elif action == "subscribe":
                # Subscribe to a session
                target_session = payload.get("session_id")
                if target_session:
                    async with connection_manager._lock:
                        if target_session not in connection_manager._connections:
                            connection_manager._connections[target_session] = []
                        if websocket not in connection_manager._connections[target_session]:
                            connection_manager._connections[target_session].append(websocket)

                    await websocket.send_json(
                        {
                            "type": "response",
                            "id": msg_id,
                            "payload": {
                                "action": "subscribed",
                                "session_id": target_session,
                            },
                        }
                    )

            else:
                # Unknown action
                await websocket.send_json(
                    {
                        "type": "error",
                        "id": msg_id,
                        "payload": {
                            "error": f"Unknown action: {action}",
                            "code": "UNKNOWN_ACTION",
                        },
                    }
                )

    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket, session_id)
    except Exception:
        await connection_manager.disconnect(websocket, session_id)
        raise


async def handle_prompt(websocket: WebSocket, msg_id: str, payload: dict[str, Any]) -> None:
    """Handle a prompt request via WebSocket.

    Args:
        websocket: The WebSocket connection.
        msg_id: The message ID.
        payload: The request payload.
    """
    session_id = payload.get("session_id")
    content = payload.get("content", "")

    if not session_id:
        await websocket.send_json(
            {
                "type": "error",
                "id": msg_id,
                "payload": {"error": "session_id is required", "code": "MISSING_SESSION_ID"},
            }
        )
        return

    session_manager = get_session_manager()

    try:
        # Send start event
        await websocket.send_json(
            {
                "type": "event",
                "id": msg_id,
                "payload": {
                    "kind": EventType.MESSAGE_START.value,
                    "session_id": session_id,
                },
            }
        )

        # Stream response
        async for chunk in session_manager.prompt_session(
            session_id=session_id,
            content=content,
            stream=True,
        ):
            if isinstance(chunk, str):
                await websocket.send_json(
                    {
                        "type": "response",
                        "id": msg_id,
                        "payload": {
                            "kind": "chunk",
                            "content": chunk,
                            "done": False,
                        },
                    }
                )
            elif hasattr(chunk, "content"):
                await websocket.send_json(
                    {
                        "type": "response",
                        "id": msg_id,
                        "payload": {
                            "kind": "chunk",
                            "content": chunk.content,
                            "done": False,
                        },
                    }
                )

        # Send complete event
        await websocket.send_json(
            {
                "type": "response",
                "id": msg_id,
                "payload": {
                    "kind": "complete",
                    "session_id": session_id,
                },
            }
        )

    except SessionNotFoundError:
        await websocket.send_json(
            {
                "type": "error",
                "id": msg_id,
                "payload": {
                    "error": f"Session not found: {session_id}",
                    "code": "SESSION_NOT_FOUND",
                },
            }
        )
    except Exception as e:
        await websocket.send_json(
            {
                "type": "error",
                "id": msg_id,
                "payload": {
                    "error": str(e),
                    "code": "PROMPT_ERROR",
                },
            }
        )


async def handle_cancel(websocket: WebSocket, msg_id: str, payload: dict[str, Any]) -> None:
    """Handle a cancel request via WebSocket.

    Args:
        websocket: The WebSocket connection.
        msg_id: The message ID.
        payload: The request payload.
    """
    session_id = payload.get("session_id")
    force = payload.get("force", False)

    if not session_id:
        await websocket.send_json(
            {
                "type": "error",
                "id": msg_id,
                "payload": {"error": "session_id is required", "code": "MISSING_SESSION_ID"},
            }
        )
        return

    session_manager = get_session_manager()

    try:
        await session_manager.cancel_session(session_id, force=force)

        await websocket.send_json(
            {
                "type": "response",
                "id": msg_id,
                "payload": {
                    "action": "cancelled",
                    "session_id": session_id,
                },
            }
        )

    except SessionNotFoundError:
        await websocket.send_json(
            {
                "type": "error",
                "id": msg_id,
                "payload": {
                    "error": f"Session not found: {session_id}",
                    "code": "SESSION_NOT_FOUND",
                },
            }
        )


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager."""
    return connection_manager
