"""AMCP Server routes package."""

from .agents import router as agents_router
from .health import router as health_router
from .sessions import router as sessions_router
from .tools import router as tools_router

__all__ = [
    "health_router",
    "sessions_router",
    "tools_router",
    "agents_router",
]
