"""Server configuration for AMCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CORSConfig(BaseModel):
    """CORS configuration."""

    enabled: bool = True
    allow_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:*",
            "http://127.0.0.1:*",
            "tauri://localhost",
        ]
    )
    allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    allow_headers: list[str] = Field(default_factory=lambda: ["*"])
    allow_credentials: bool = True


class AuthConfig(BaseModel):
    """Authentication configuration."""

    enabled: bool = False
    api_key: str | None = None


class ServerConfig(BaseModel):
    """AMCP Server configuration."""

    host: str = "127.0.0.1"
    port: int = 4096
    cors: CORSConfig = Field(default_factory=CORSConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # Session settings
    session_timeout_minutes: int = 60 * 24  # 24 hours
    max_sessions: int = 100

    # Working directory
    work_dir: Path | None = None

    # Agent settings
    default_agent: str = "default"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerConfig:
        """Create config from dictionary."""
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump()


# Global server config instance
_server_config: ServerConfig | None = None


def get_server_config() -> ServerConfig:
    """Get the global server configuration."""
    global _server_config
    if _server_config is None:
        _server_config = ServerConfig()
    return _server_config


def set_server_config(config: ServerConfig) -> None:
    """Set the global server configuration."""
    global _server_config
    _server_config = config


def reset_server_config() -> None:
    """Reset server configuration to default."""
    global _server_config
    _server_config = None
