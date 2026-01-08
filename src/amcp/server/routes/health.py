"""Health and info endpoints."""

from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter

from ..._version import __version__
from ..config import get_server_config
from ..models import HealthResponse, ServerInfo
from ..session_manager import get_session_manager

router = APIRouter(tags=["health"])

# Track server start time
_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check server health.

    Returns basic health information and uptime.
    """
    return HealthResponse(
        healthy=True,
        version=__version__,
        uptime_seconds=time.time() - _start_time,
    )


@router.get("/info", response_model=ServerInfo)
async def server_info() -> ServerInfo:
    """Get server information.

    Returns detailed information about the server including
    available capabilities, agents, and tools.
    """
    from ...multi_agent import get_agent_registry
    from ...tools import get_tool_registry

    registry = get_agent_registry()

    # Get agent names
    agent_names = list(registry._agents.keys()) if hasattr(registry, "_agents") else []

    # Get tools count
    try:
        tool_registry = get_tool_registry()
        tools_count = len(tool_registry.list_tools())
    except Exception:
        tools_count = 0

    return ServerInfo(
        name="amcp-server",
        version=__version__,
        protocol_version="1.0",
        capabilities=[
            "sessions",
            "streaming",
            "websocket",
            "sse",
            "tools",
            "agents",
        ],
        agents=agent_names,
        tools_count=tools_count,
    )


@router.get("/status")
async def server_status() -> dict:
    """Get detailed server status.

    Returns session counts and resource usage.
    """
    from ..websocket import get_connection_manager

    session_manager = get_session_manager()
    config = get_server_config()
    connection_manager = get_connection_manager()

    sessions = await session_manager.list_sessions()
    busy_count = sum(1 for s in sessions if s.status.value == "busy")
    connection_stats = connection_manager.get_connection_stats()

    return {
        "timestamp": datetime.now().isoformat(),
        "version": __version__,
        "uptime_seconds": time.time() - _start_time,
        "sessions": {
            "total": len(sessions),
            "busy": busy_count,
            "idle": len(sessions) - busy_count,
            "max": config.max_sessions,
        },
        "connections": connection_stats,
        "config": {
            "host": config.host,
            "port": config.port,
            "work_dir": str(config.work_dir) if config.work_dir else None,
        },
    }


@router.get("/connections")
async def connection_status() -> dict:
    """Get WebSocket connection status.

    Returns the number of connected clients globally and per session.
    """
    from ..websocket import get_connection_manager

    connection_manager = get_connection_manager()
    stats = connection_manager.get_connection_stats()

    return {
        "timestamp": datetime.now().isoformat(),
        **stats,
    }
