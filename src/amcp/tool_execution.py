"""Capability-safe tool-call normalization and execution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AMCPConfig
from .mcp_client import call_mcp_tool
from .mcp_naming import is_mcp_tool_name
from .task import TaskManager, TaskTool
from .tools import ToolRegistry, ToolResult


class ToolCallProtocolError(Exception):
    """Raised for provider tool-call structures that cannot be repaired."""

    def __init__(self, message: str, tool_calls: Any | None = None) -> None:
        super().__init__(message)
        self.tool_calls = tool_calls


class ToolPermissionError(Exception):
    """Raised when a tool call is outside the effective capability."""


class WorkspaceBoundaryError(Exception):
    """Raised when a tool attempts to escape its runtime workspace."""


@dataclass(frozen=True)
class ToolExecutionContext:
    """Trusted runtime context unavailable for model modification."""

    session_id: str
    workspace_root: Path
    turn_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", self.workspace_root.expanduser().resolve())

    def resolve_path(self, value: str) -> Path:
        """Resolve a model path and reject workspace escapes."""
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.workspace_root):
            raise WorkspaceBoundaryError(f"Path is outside workspace: {value}")
        return resolved


@dataclass(frozen=True)
class ToolCapability:
    """Effective allowlist shared by tool display and execution."""

    configured_tools: frozenset[str] | None
    excluded_tools: frozenset[str]
    can_delegate: bool

    @classmethod
    def from_spec(
        cls,
        tools: list[str] | None,
        exclude_tools: list[str] | None,
        can_delegate: bool,
    ) -> ToolCapability:
        """Build a capability from resolved agent configuration."""
        return cls(
            configured_tools=frozenset(tools) if tools is not None else None,
            excluded_tools=frozenset(exclude_tools or []),
            can_delegate=can_delegate,
        )

    def allows(self, tool_name: str) -> bool:
        """Return whether this capability allows a named tool."""
        if tool_name in self.excluded_tools:
            return False
        if tool_name == "task" and not self.can_delegate:
            return False
        return self.configured_tools is None or tool_name in self.configured_tools


@dataclass(frozen=True)
class NormalizedToolCall:
    """Provider tool call normalized for validation and dispatch."""

    id: str
    name: str
    raw_arguments: str
    arguments: dict[str, Any] | None
    argument_error: str | None = None
    extra_content: dict[str, Any] | None = None


def normalize_tool_calls(tool_calls: Any) -> list[NormalizedToolCall]:
    """Normalize provider tool calls and classify repairable argument errors."""
    if not isinstance(tool_calls, list):
        raise ToolCallProtocolError("Provider tool_calls must be a list", tool_calls=tool_calls)

    normalized: list[NormalizedToolCall] = []
    seen_ids: set[str] = set()
    for index, call in enumerate(tool_calls):
        if not isinstance(call, dict):
            raise ToolCallProtocolError(f"Tool call {index} must be an object")
        call_id = call.get("id")
        name = call.get("name")
        if not isinstance(call_id, str) or not call_id.strip():
            raise ToolCallProtocolError(f"Tool call {index} is missing a valid ID")
        if call_id in seen_ids:
            raise ToolCallProtocolError(f"Duplicate tool call ID: {call_id}", tool_calls=tool_calls)
        seen_ids.add(call_id)
        if not isinstance(name, str) or not name.strip():
            raise ToolCallProtocolError(f"Tool call {call_id} is missing a valid name")

        raw = call.get("arguments", "{}")
        if raw is None:
            raw = "{}"
        if isinstance(raw, dict):
            arguments = raw
            raw_arguments = json.dumps(raw, ensure_ascii=False)
            error = None
        elif isinstance(raw, str):
            raw_arguments = raw or "{}"
            try:
                parsed = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                arguments = None
                error = f"Invalid JSON arguments: {exc.msg}"
            else:
                if not isinstance(parsed, dict):
                    arguments = None
                    error = "Tool arguments must be a JSON object"
                else:
                    arguments = parsed
                    error = None
        else:
            raw_arguments = json.dumps(raw, ensure_ascii=False)
            arguments = None
            error = "Tool arguments must be a JSON object"

        normalized.append(
            NormalizedToolCall(
                id=call_id,
                name=name,
                raw_arguments=raw_arguments,
                arguments=arguments,
                argument_error=error,
                extra_content=call.get("extra_content") if isinstance(call.get("extra_content"), dict) else None,
            )
        )
    return normalized


class ToolExecutor:
    """Execute allowed built-in and MCP tools within a trusted workspace."""

    def __init__(
        self,
        *,
        context: ToolExecutionContext,
        capability: ToolCapability,
        exposed_tools: set[str],
        registry: ToolRegistry,
        mcp_registry: dict[str, tuple[str, str]],
        config: AMCPConfig,
        task_manager: TaskManager | None = None,
    ):
        self.context = context
        self.capability = capability
        self.exposed_tools = exposed_tools
        self.registry = registry
        self.mcp_registry = mcp_registry
        self.config = config
        self.task_manager = task_manager

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Validate permission and execute one tool asynchronously."""
        if name not in self.exposed_tools or not self.capability.allows(name):
            raise ToolPermissionError(f"Tool '{name}' is not authorized for this turn")

        arguments = self.prepare_model_arguments(name, arguments)
        args = self._bind_arguments(name, arguments)
        if is_mcp_tool_name(name):
            return await self._execute_mcp(name, args)
        if name == "task":
            if self.task_manager is None:
                return ToolResult(success=False, content="", error="Task manager is not configured")
            content = await TaskTool(
                manager=self.task_manager,
                session_id=self.context.session_id,
                work_dir=self.context.workspace_root,
            ).execute(**args)
            return ToolResult(success=True, content=content)
        if name == "bash":
            return await self._execute_bash(args)
        return await self._execute_sync_tool(name, args)

    async def _execute_sync_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Run a thread-backed tool and settle it before propagating cancellation.

        Python cannot stop a thread that has already entered synchronous tool
        code. Shielding the worker means a cancelled turn waits until any file,
        memory, or external side effect has reached a known terminal state.
        """
        task = asyncio.create_task(
            asyncio.to_thread(self.registry.execute_tool, name, **arguments),
            name=f"amcp-tool-{self.context.turn_id}-{name}",
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancelled:
            # Repeated cancellation requests must not break the settled
            # guarantee while the underlying thread can still mutate state.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                with contextlib.suppress(Exception):
                    task.result()
            raise cancelled

    def prepare_model_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Canonicalize model input before hooks or trusted runtime binding."""
        if is_mcp_tool_name(name):
            return dict(arguments)
        return self.registry.prepare_model_arguments(name, arguments)

    def _bind_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        args = dict(arguments)
        if name in {"read_file", "write_file"} and isinstance(args.get("path"), str):
            args["path"] = str(self.context.resolve_path(args["path"]))
        elif name == "grep":
            paths = args.get("paths")
            if paths is None:
                args["paths"] = [str(self.context.workspace_root)]
            elif isinstance(paths, list):
                args["paths"] = [str(self.context.resolve_path(path)) for path in paths]
        elif name == "apply_patch":
            args["_workspace_root"] = self.context.workspace_root
        elif name == "bash":
            args.pop("cwd", None)
        elif name == "memory":
            args["project_root"] = str(self.context.workspace_root)
        return args

    async def _execute_mcp(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        server_name, inner_name = self.mcp_registry.get(name, (None, None))
        if not server_name or not inner_name:
            return ToolResult(success=False, content="", error=f"Unknown MCP tool {name}")
        server = self.config.servers.get(server_name)
        if server is None:
            return ToolResult(success=False, content="", error=f"Unknown MCP server {server_name}")
        response = await call_mcp_tool(server, inner_name, arguments)
        parts = [item.get("text", "") for item in response.get("content", []) or [] if item.get("type") == "text"]
        content = "\n\n".join(parts) or json.dumps(response, ensure_ascii=False)
        return ToolResult(success=True, content=content, metadata={"response": response})

    async def _execute_bash(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments.get("command")
        timeout = arguments.get("timeout", 30)
        if not isinstance(command, str):
            return ToolResult(success=False, content="", error="Bash command must be a string")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1 or timeout > 600:
            return ToolResult(success=False, content="", error="Bash timeout must be between 1 and 600")

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.context.workspace_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            await self._terminate_process(process)
            return ToolResult(success=False, content="", error=f"Command timed out after {timeout} seconds")
        except asyncio.CancelledError:
            await self._terminate_process(process)
            raise

        output = stdout.decode(errors="replace")
        if stderr:
            output += f"\n[stderr]\n{stderr.decode(errors='replace')}"
        output = output or "(no output)"
        max_chars = 6000
        truncated = len(output) > max_chars
        if truncated:
            half = (max_chars - 40) // 2
            output = f"{output[:half]}\n... [output truncated] ...\n{output[-half:]}"
        return ToolResult(
            success=process.returncode == 0,
            content=output,
            metadata={
                "command": command,
                "exit_code": process.returncode,
                "cwd": str(self.context.workspace_root),
                "truncated": truncated,
            },
            error=None if process.returncode == 0 else f"Command exited with code {process.returncode}",
        )

    @staticmethod
    async def _terminate_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
