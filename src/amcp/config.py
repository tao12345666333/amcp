from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import tomli_w  # type: ignore

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "amcp"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass
class Server:
    # stdio transport fields
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # http(sse) transport fields
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ChatConfig:
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_type: str | None = None  # "openai" (default) or "anthropic"
    # Tool calling settings
    tool_loop_limit: int | None = None
    default_max_lines: int | None = None
    read_roots: list[str] | None = None  # list of allowed root paths for read_file
    # MCP tool exposure
    mcp_tools_enabled: bool | None = None
    mcp_servers: list[str] | None = None  # which servers' tools to expose; if unset, expose all configured servers
    # Built-in file modification tools
    write_tool_enabled: bool | None = None
    edit_tool_enabled: bool | None = None


@dataclass
class AMCPConfig:
    servers: dict[str, Server]
    chat: ChatConfig | None = None


_DEFAULT = {
    "servers": {
        "exa": {
            "url": "https://mcp.exa.ai/mcp",
        }
    },
    "chat": {
        "base_url": "https://inference.baseten.co/v1",
        "model": "zai-org/GLM-4.6",
        # "api_key": ""  # optional; users can add this if they want config-based auth
        "tool_loop_limit": 5,
        "default_max_lines": 400,
        # "read_roots": ["."]  # optional; defaults to current working directory when unset
        "mcp_tools_enabled": True,
        # "mcp_servers": ["exa"]  # optional; if unset, expose all configured servers
        "write_tool_enabled": True,
        "edit_tool_enabled": True,
    },
}


def _decode_server(name: str, raw: Mapping[str, object]) -> Server:
    command = raw.get("command")
    command_s = str(command) if command is not None else None
    args = [str(x) for x in (raw.get("args") or [])]
    env = {str(k): str(v) for k, v in (raw.get("env") or {}).items()}
    url = raw.get("url")
    url_s = str(url) if url is not None else None
    headers = {str(k): str(v) for k, v in (raw.get("headers") or {}).items()}
    return Server(command=command_s, args=args, env=env, url=url_s, headers=headers)


def _decode_chat(raw: Mapping[str, object] | None) -> ChatConfig | None:
    if not raw:
        return None
    base_url = raw.get("base_url")
    model = raw.get("model")
    api_key = raw.get("api_key")
    api_type = raw.get("api_type")
    tool_loop_limit = raw.get("tool_loop_limit")
    default_max_lines = raw.get("default_max_lines")
    read_roots = raw.get("read_roots")
    mcp_tools_enabled = raw.get("mcp_tools_enabled")
    mcp_servers = raw.get("mcp_servers")
    write_tool_enabled = raw.get("write_tool_enabled")
    edit_tool_enabled = raw.get("edit_tool_enabled")
    return ChatConfig(
        base_url=str(base_url) if base_url is not None else None,
        model=str(model) if model is not None else None,
        api_key=str(api_key) if api_key is not None else None,
        api_type=str(api_type) if api_type is not None else None,
        tool_loop_limit=int(tool_loop_limit) if tool_loop_limit is not None else None,
        default_max_lines=int(default_max_lines) if default_max_lines is not None else None,
        read_roots=[str(p) for p in (read_roots or [])] if read_roots is not None else None,
        mcp_tools_enabled=bool(mcp_tools_enabled) if mcp_tools_enabled is not None else None,
        mcp_servers=[str(s) for s in (mcp_servers or [])] if mcp_servers is not None else None,
        write_tool_enabled=bool(write_tool_enabled) if write_tool_enabled is not None else None,
        edit_tool_enabled=bool(edit_tool_enabled) if edit_tool_enabled is not None else None,
    )


def load_config() -> AMCPConfig:
    data = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else _DEFAULT
    servers = {name: _decode_server(name, raw) for name, raw in data.get("servers", {}).items()}
    chat = _decode_chat(data.get("chat"))
    return AMCPConfig(servers=servers, chat=chat)


def _encode_server(s: Server) -> dict:
    out: dict = {}
    if s.command:
        out["command"] = s.command
    if s.args:
        out["args"] = list(s.args)
    if s.env:
        out["env"] = dict(s.env)
    if s.url:
        out["url"] = s.url
    if s.headers:
        out["headers"] = dict(s.headers)
    return out


def _encode_chat(c: ChatConfig | None) -> dict | None:
    if c is None:
        return None
    out: dict = {}
    if c.base_url:
        out["base_url"] = c.base_url
    if c.model:
        out["model"] = c.model
    if c.api_key:
        out["api_key"] = c.api_key
    if c.api_type:
        out["api_type"] = c.api_type
    if c.tool_loop_limit is not None:
        out["tool_loop_limit"] = int(c.tool_loop_limit)
    if c.default_max_lines is not None:
        out["default_max_lines"] = int(c.default_max_lines)
    if c.read_roots is not None:
        out["read_roots"] = list(c.read_roots)
    if c.mcp_tools_enabled is not None:
        out["mcp_tools_enabled"] = bool(c.mcp_tools_enabled)
    if c.mcp_servers is not None:
        out["mcp_servers"] = list(c.mcp_servers)
    if c.write_tool_enabled is not None:
        out["write_tool_enabled"] = bool(c.write_tool_enabled)
    if c.edit_tool_enabled is not None:
        out["edit_tool_enabled"] = bool(c.edit_tool_enabled)
    return out


def save_config(cfg: AMCPConfig) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {"servers": {name: _encode_server(s) for name, s in cfg.servers.items()}}
    chat_obj = _encode_chat(cfg.chat)
    if chat_obj is not None:
        data["chat"] = chat_obj
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(data, f)
    return CONFIG_FILE


def save_default_config() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "wb") as f:
            tomli_w.dump(_DEFAULT, f)
    return CONFIG_FILE
