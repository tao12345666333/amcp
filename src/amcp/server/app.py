"""FastAPI application for AMCP Server."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .._version import __version__
from .config import ServerConfig, get_server_config, set_server_config
from .events import router as events_router
from .routes import agents_router, health_router, sessions_router, tools_router
from .session_manager import SessionManager, set_session_manager
from .websocket import router as websocket_router

# Global app instance
_app: FastAPI | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Handles startup and shutdown events.
    """
    # Startup
    config = get_server_config()
    print(f"🚀 AMCP Server v{__version__} starting...")
    print(f"   Host: {config.host}")
    print(f"   Port: {config.port}")
    print(f"   Working directory: {config.work_dir or 'current directory'}")

    # Initialize session manager
    session_manager = SessionManager(config)
    set_session_manager(session_manager)

    yield

    # Shutdown
    print("\n👋 AMCP Server shutting down...")


def create_app(config: ServerConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Optional server configuration. Uses default if not provided.

    Returns:
        Configured FastAPI application.
    """
    global _app

    # Set configuration
    if config:
        set_server_config(config)

    cfg = get_server_config()

    # Create FastAPI app
    app = FastAPI(
        title="AMCP Server",
        description="AI Coding Agent Server with HTTP/WebSocket API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Configure CORS
    if cfg.cors.enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors.allow_origins,
            allow_credentials=cfg.cors.allow_credentials,
            allow_methods=cfg.cors.allow_methods,
            allow_headers=cfg.cors.allow_headers,
        )

    # Add exception handlers
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle uncaught exceptions."""
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc),
                "code": "INTERNAL_ERROR",
                "details": None,
            },
        )

    # Include routers with /api/v1 prefix
    api_prefix = "/api/v1"
    app.include_router(health_router, prefix=api_prefix)
    app.include_router(sessions_router, prefix=api_prefix)
    app.include_router(tools_router, prefix=api_prefix)
    app.include_router(agents_router, prefix=api_prefix)
    app.include_router(events_router, prefix=api_prefix)

    # Include WebSocket router (at root level)
    app.include_router(websocket_router)

    # Add root endpoint
    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "name": "amcp-server",
            "version": __version__,
            "api": f"{api_prefix}",
            "docs": "/docs",
            "health": f"{api_prefix}/health",
        }

    # Store app globally
    _app = app

    return app


def get_app() -> FastAPI:
    """Get the global FastAPI application.

    Creates a new app with default config if not yet created.

    Returns:
        The FastAPI application.
    """
    global _app
    if _app is None:
        _app = create_app()
    return _app


def run_server(
    host: str = "127.0.0.1",
    port: int = 4096,
    work_dir: str | None = None,
    reload: bool = False,
) -> None:
    """Run the AMCP server.

    Args:
        host: Host to bind to.
        port: Port to listen on.
        work_dir: Working directory for sessions.
        reload: Enable auto-reload for development.
    """
    from pathlib import Path

    import uvicorn

    # Create configuration
    config = ServerConfig(
        host=host,
        port=port,
        work_dir=Path(work_dir) if work_dir else None,
    )
    set_server_config(config)

    # Create app
    app = create_app(config)

    # Run with uvicorn
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
