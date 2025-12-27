"""ACP (Agent Client Protocol) support for AMCP.

This module implements a full ACP-compliant agent with support for:
- Session management (new, load, list)
- Session modes (ask, architect, code)
- Slash commands
- Agent plans
- Tool calls with permission requests
- Client filesystem and terminal capabilities
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from acp import (
    Agent,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    run_agent,
    start_tool_call,
    text_block,
    update_agent_message,
    update_agent_thought,
    update_tool_call,
)
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities,
    AudioContentBlock,
    AvailableCommand,
    AvailableCommandInput,
    ClientCapabilities,
    EmbeddedResourceContentBlock,
    HttpMcpServer,
    ImageContentBlock,
    Implementation,
    McpServerStdio,
    PlanEntry,
    PromptCapabilities,
    ResourceContentBlock,
    SessionMode,
    SessionModeState,
    SseMcpServer,
    TextContentBlock,
    ToolCallStatus,
    UnstructuredCommandInput,
)

from .agent_spec import ResolvedAgentSpec, get_default_agent_spec
from .config import load_config
from .llm import create_llm_client
from .mcp_client import call_mcp_tool, list_mcp_tools
from .tools import ToolResult, get_tool_registry

# Session modes
AVAILABLE_MODES = [
    SessionMode(id="ask", name="Ask", description="Request permission before making any changes"),
    SessionMode(id="architect", name="Architect", description="Design and plan without implementation"),
    SessionMode(id="code", name="Code", description="Write and modify code with full tool access"),
]

# Slash commands
AVAILABLE_COMMANDS = [
    AvailableCommand(name="clear", description="Clear conversation history"),
    AvailableCommand(
        name="plan",
        description="Create a detailed implementation plan",
        input=AvailableCommandInput(UnstructuredCommandInput(hint="description of what to plan")),
    ),
    AvailableCommand(
        name="search",
        description="Search for patterns in files",
        input=AvailableCommandInput(UnstructuredCommandInput(hint="pattern to search")),
    ),
    AvailableCommand(name="help", description="Show available commands"),
]


class ACPSession:
    """Represents an ACP session with conversation history."""

    def __init__(self, session_id: str, cwd: str):
        self.session_id = session_id
        self.cwd = cwd
        self.conversation_history: list[dict[str, Any]] = []
        self.tool_calls_history: list[dict[str, Any]] = []
        self.created_at = datetime.now().isoformat()
        self.current_mode_id = "ask"
        self.plan_entries: list[dict[str, Any]] = []

    def add_user_message(self, content: str) -> None:
        self.conversation_history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self.conversation_history.append({"role": "assistant", "content": content})

    def add_tool_call(self, tool_name: str, args: dict[str, Any], result: str) -> None:
        self.tool_calls_history.append(
            {
                "tool": tool_name,
                "args": args,
                "result": result,
                "timestamp": datetime.now().isoformat(),
            }
        )


class AMCPAgent(Agent):
    """ACP-compliant agent implementation for AMCP."""

    def __init__(self, agent_spec: ResolvedAgentSpec | None = None):
        self.agent_spec = agent_spec or get_default_agent_spec()
        self._conn: Client | None = None
        self._sessions: dict[str, ACPSession] = {}
        self._cancelled_sessions: set[str] = set()
        self._client_capabilities: ClientCapabilities | None = None

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        """Handle initialization request from client."""
        self._client_capabilities = client_capabilities
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    image=False,
                    audio=False,
                    embedded_context=True,
                ),
            ),
            agent_info=Implementation(
                name="amcp",
                title="AMCP Agent",
                version="0.4.1",
            ),
        )

    async def new_session(
        self,
        cwd: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio],
        **kwargs: Any,
    ) -> NewSessionResponse:
        """Create a new conversation session."""
        session_id = uuid4().hex
        self._sessions[session_id] = ACPSession(session_id, cwd)

        # Send available commands after session creation
        if self._conn:
            await self._send_available_commands(session_id)

        return NewSessionResponse(
            session_id=session_id,
            modes=SessionModeState(
                current_mode_id="ask",
                available_modes=AVAILABLE_MODES,
            ),
        )

    async def _send_available_commands(self, session_id: str) -> None:
        """Send available slash commands to client."""
        if self._conn:
            from acp.schema import AvailableCommandsUpdate

            await self._conn.session_update(
                session_id=session_id,
                update=AvailableCommandsUpdate(
                    session_update="available_commands_update",
                    available_commands=AVAILABLE_COMMANDS,
                ),
            )

    async def load_session(
        self,
        cwd: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio],
        session_id: str,
        **kwargs: Any,
    ) -> LoadSessionResponse | None:
        """Load an existing session."""
        if session_id not in self._sessions:
            session_file = Path.home() / ".config" / "amcp" / "acp_sessions" / f"{session_id}.json"
            if session_file.exists():
                try:
                    data = json.loads(session_file.read_text(encoding="utf-8"))
                    session = ACPSession(session_id, cwd)
                    session.conversation_history = data.get("conversation_history", [])
                    session.tool_calls_history = data.get("tool_calls_history", [])
                    session.current_mode_id = data.get("current_mode_id", "ask")
                    self._sessions[session_id] = session
                except Exception:
                    return None
            else:
                return None

        session = self._sessions[session_id]
        session.cwd = cwd

        # Replay conversation history
        if self._conn:
            for msg in session.conversation_history:
                if msg["role"] == "user":
                    from acp.schema import UserMessageChunk

                    await self._conn.session_update(
                        session_id=session_id,
                        update=UserMessageChunk(
                            session_update="user_message_chunk",
                            content=text_block(msg["content"]),
                        ),
                    )
                elif msg["role"] == "assistant":
                    await self._conn.session_update(
                        session_id=session_id,
                        update=update_agent_message(text_block(msg["content"])),
                    )
            await self._send_available_commands(session_id)

        return LoadSessionResponse()

    async def prompt(
        self,
        prompt: list[
            TextContentBlock
            | ImageContentBlock
            | AudioContentBlock
            | ResourceContentBlock
            | EmbeddedResourceContentBlock
        ],
        session_id: str,
        **kwargs: Any,
    ) -> PromptResponse:
        """Handle a prompt from the client."""
        if session_id not in self._sessions:
            return PromptResponse(stop_reason="refusal")

        session = self._sessions[session_id]
        self._cancelled_sessions.discard(session_id)

        user_text = self._extract_text_from_prompt(prompt)

        # Handle slash commands
        if user_text.startswith("/"):
            return await self._handle_slash_command(session, user_text)

        session.add_user_message(user_text)

        try:
            response = await self._process_prompt(session, user_text)
            session.add_assistant_message(response)
            self._save_session(session)
            return PromptResponse(stop_reason="end_turn")
        except asyncio.CancelledError:
            return PromptResponse(stop_reason="cancelled")
        except Exception as e:
            if self._conn:
                await self._conn.session_update(
                    session_id=session_id,
                    update=update_agent_message(text_block(f"Error: {e}")),
                )
            return PromptResponse(stop_reason="refusal")

    async def _handle_slash_command(self, session: ACPSession, text: str) -> PromptResponse:
        """Handle slash commands."""
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "clear":
            session.conversation_history = []
            session.tool_calls_history = []
            if self._conn:
                await self._conn.session_update(
                    session_id=session.session_id,
                    update=update_agent_message(text_block("Conversation history cleared.")),
                )
        elif cmd == "help":
            help_text = "Available commands:\n" + "\n".join(
                f"  /{c.name} - {c.description}" for c in AVAILABLE_COMMANDS
            )
            if self._conn:
                await self._conn.session_update(
                    session_id=session.session_id,
                    update=update_agent_message(text_block(help_text)),
                )
        elif cmd == "plan":
            return await self._create_plan(session, arg)
        elif cmd == "search":
            return await self._search_files(session, arg)
        else:
            if self._conn:
                await self._conn.session_update(
                    session_id=session.session_id,
                    update=update_agent_message(text_block(f"Unknown command: /{cmd}")),
                )

        return PromptResponse(stop_reason="end_turn")

    async def _create_plan(self, session: ACPSession, description: str) -> PromptResponse:
        """Create an execution plan."""
        if not description:
            if self._conn:
                await self._conn.session_update(
                    session_id=session.session_id,
                    update=update_agent_message(text_block("Usage: /plan <description>")),
                )
            return PromptResponse(stop_reason="end_turn")

        # Send initial plan
        if self._conn:
            from acp.schema import Plan

            await self._conn.session_update(
                session_id=session.session_id,
                update=Plan(
                    session_update="plan",
                    entries=[
                        PlanEntry(content="Analyzing requirements...", priority="high", status="in_progress"),
                    ],
                ),
            )

        # Process with LLM to generate plan
        session.add_user_message(f"Create a detailed implementation plan for: {description}")
        response = await self._process_prompt(session, f"Create a step-by-step plan for: {description}")
        session.add_assistant_message(response)

        # Parse response into plan entries
        lines = [
            line.strip()
            for line in response.split("\n")
            if line.strip() and (line.strip().startswith("-") or line.strip()[0].isdigit())
        ]
        entries = [
            PlanEntry(content=line.lstrip("-0123456789. "), priority="medium", status="pending") for line in lines[:10]
        ]
        if entries and self._conn:
            from acp.schema import Plan

            await self._conn.session_update(
                session_id=session.session_id,
                update=Plan(session_update="plan", entries=entries),
            )

        self._save_session(session)
        return PromptResponse(stop_reason="end_turn")

    async def _search_files(self, session: ACPSession, pattern: str) -> PromptResponse:
        """Search for patterns in files."""
        if not pattern:
            if self._conn:
                await self._conn.session_update(
                    session_id=session.session_id,
                    update=update_agent_message(text_block("Usage: /search <pattern>")),
                )
            return PromptResponse(stop_reason="end_turn")

        tool_call_id = f"call_{uuid4().hex[:8]}"
        if self._conn:
            await self._conn.session_update(
                session_id=session.session_id,
                update=start_tool_call(tool_call_id=tool_call_id, title=f"Searching: {pattern}", kind="search"),
            )

        # Execute grep
        registry = get_tool_registry()
        result = registry.execute_tool("grep", pattern=pattern, path=session.cwd)

        if self._conn:
            await self._conn.session_update(
                session_id=session.session_id,
                update=update_tool_call(
                    tool_call_id=tool_call_id,
                    status=ToolCallStatus.completed if result.success else ToolCallStatus.failed,
                    content=[
                        {
                            "type": "content",
                            "content": text_block(
                                result.content if result.success else result.error or "Search failed"
                            ),
                        }
                    ],
                ),
            )

        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        """Cancel ongoing operations for a session."""
        self._cancelled_sessions.add(session_id)

    async def authenticate(self, method_id: str, **kwargs: Any) -> None:
        """Handle authentication (not required for AMCP)."""
        return None

    async def set_session_mode(self, mode_id: str, session_id: str, **kwargs: Any) -> None:
        """Set session mode."""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            if mode_id in ("ask", "architect", "code"):
                session.current_mode_id = mode_id
                if self._conn:
                    from acp.schema import CurrentModeUpdate

                    await self._conn.session_update(
                        session_id=session_id,
                        update=CurrentModeUpdate(session_update="current_mode_update", mode_id=mode_id),
                    )

    async def set_session_model(self, model_id: str, session_id: str, **kwargs: Any) -> None:
        """Set session model (not implemented)."""
        return None

    async def list_sessions(self, cursor: str | None = None, cwd: str | None = None, **kwargs: Any):
        """List available sessions."""
        from acp.schema import ListSessionsResponse, SessionInfo

        sessions = []
        for sid, session in self._sessions.items():
            sessions.append(SessionInfo(session_id=sid, title=f"Session {sid[:8]}", cwd=session.cwd))
        return ListSessionsResponse(sessions=sessions)

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Handle extension methods."""
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        """Handle extension notifications."""
        pass

    def _extract_text_from_prompt(
        self,
        prompt: list[
            TextContentBlock
            | ImageContentBlock
            | AudioContentBlock
            | ResourceContentBlock
            | EmbeddedResourceContentBlock
        ],
    ) -> str:
        """Extract text content from prompt blocks."""
        parts = []
        for block in prompt:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "resource":
                    resource = block.get("resource", {})
                    if "text" in resource:
                        parts.append(f"[File: {resource.get('uri', 'unknown')}]\n{resource['text']}")
            elif hasattr(block, "text"):
                parts.append(getattr(block, "text", ""))
        return "\n".join(parts)

    async def _process_prompt(self, session: ACPSession, user_text: str) -> str:
        """Process prompt with LLM and tools."""
        cfg = load_config()
        llm_client = create_llm_client(cfg.chat)

        system_prompt = self._get_system_prompt(session)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(session.conversation_history)

        tools = await self._build_tools(session)
        tool_registry = await self._build_tool_registry()

        max_steps = self.agent_spec.max_steps
        for _step in range(max_steps):
            if session.session_id in self._cancelled_sessions:
                raise asyncio.CancelledError()

            resp = llm_client.chat(messages=messages, tools=tools if tools else None)

            # Send thinking content if available
            if resp.thinking and self._conn:
                await self._conn.session_update(
                    session_id=session.session_id,
                    update=update_agent_thought(text_block(resp.thinking)),
                )

            if not resp.tool_calls:
                final_text = resp.content or ""
                if self._conn:
                    await self._conn.session_update(
                        session_id=session.session_id,
                        update=update_agent_message(text_block(final_text)),
                    )
                return final_text

            for tc in resp.tool_calls:
                tool_name = tc["name"]
                args = json.loads(tc["arguments"] or "{}")
                tool_call_id = f"call_{uuid4().hex[:8]}"

                # Request permission in "ask" mode for write operations
                if session.current_mode_id == "ask" and tool_name in ("write_file", "edit_file", "bash"):
                    permission = await self._request_permission(session, tool_call_id, tool_name, args)
                    if not permission:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": tool_name,
                                "content": "Permission denied by user",
                            }
                        )
                        continue

                if self._conn:
                    await self._conn.session_update(
                        session_id=session.session_id,
                        update=start_tool_call(
                            tool_call_id=tool_call_id,
                            title=f"Executing {tool_name}",
                            kind=self._get_tool_kind(tool_name),
                        ),
                    )

                result = await self._execute_tool(tool_name, args, tool_registry, cfg, session)
                session.add_tool_call(tool_name, args, result)

                if self._conn:
                    await self._conn.session_update(
                        session_id=session.session_id,
                        update=update_tool_call(
                            tool_call_id=tool_call_id,
                            status=ToolCallStatus.completed,
                            content=[{"type": "content", "content": text_block(result[:2000])}],
                        ),
                    )

                messages.append(
                    {
                        "role": "assistant",
                        "content": resp.content or "",
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {"name": tool_name, "arguments": tc["arguments"] or "{}"},
                            }
                        ],
                    }
                )
                messages.append({"role": "tool", "tool_call_id": tc["id"], "name": tool_name, "content": result[:8000]})

        return "Maximum steps reached. Please try a simpler request."

    async def _request_permission(
        self, session: ACPSession, tool_call_id: str, tool_name: str, args: dict[str, Any]
    ) -> bool:
        """Request permission from user for tool execution."""
        if not self._conn:
            return True

        from acp.schema import PermissionOption, PermissionOptionKind, ToolCallUpdate

        try:
            response = await self._conn.request_permission(
                session_id=session.session_id,
                tool_call=ToolCallUpdate(
                    session_update="tool_call_update",
                    tool_call_id=tool_call_id,
                    title=f"Execute {tool_name}",
                    status=ToolCallStatus.pending,
                ),
                options=[
                    PermissionOption(option_id="allow", name="Allow", kind=PermissionOptionKind.allow_once),
                    PermissionOption(option_id="reject", name="Reject", kind=PermissionOptionKind.reject_once),
                ],
            )
            return response.outcome.outcome == "selected" and response.outcome.option_id == "allow"
        except Exception:
            return True

    def _get_system_prompt(self, session: ACPSession) -> str:
        """Get system prompt with context."""
        mode_prompts = {
            "ask": "You are a helpful coding assistant. Always ask for permission before making changes.",
            "architect": "You are a software architect. Focus on design and planning without implementation.",
            "code": "You are a coding assistant with full access to tools. Implement solutions directly.",
        }
        base_prompt = mode_prompts.get(session.current_mode_id, mode_prompts["ask"])

        prompt_vars = {
            "work_dir": session.cwd,
            "current_time": datetime.now().isoformat(),
            "agent_name": self.agent_spec.name,
            "mcp_tools": "[]",
        }
        try:
            custom_prompt = self.agent_spec.system_prompt.format(**prompt_vars)
        except KeyError:
            custom_prompt = self.agent_spec.system_prompt

        return f"{base_prompt}\n\n{custom_prompt}"

    async def _build_tools(self, session: ACPSession) -> list[dict[str, Any]]:
        """Build list of available tools based on mode."""
        tools = []

        # In architect mode, only provide read tools
        allowed = ("read_file", "grep", "think") if session.current_mode_id == "architect" else None

        registry = get_tool_registry()
        for tool_name in registry.list_tools():
            if allowed and tool_name not in allowed:
                continue
            tool = registry.get_tool(tool_name)
            if tool and hasattr(tool, "get_spec"):
                tools.append(tool.get_spec())

        # Load MCP tools
        cfg = load_config()
        chat_cfg = cfg.chat
        if chat_cfg and chat_cfg.mcp_tools_enabled is False:
            return tools

        selected = list(cfg.servers.keys())
        if chat_cfg and chat_cfg.mcp_servers:
            selected = [s for s in chat_cfg.mcp_servers if s in cfg.servers]

        for name in selected:
            try:
                server = cfg.servers[name]
                info_list = await list_mcp_tools(server)
                for info in info_list:
                    tname = info.get("name") or "tool"
                    oname = f"mcp.{name}.{tname}"
                    params = info.get("inputSchema") or {"type": "object"}
                    tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": oname,
                                "description": info.get("description", ""),
                                "parameters": params,
                            },
                        }
                    )
            except Exception:
                pass
        return tools

    async def _build_tool_registry(self) -> dict[str, tuple[str, str]]:
        """Build MCP tool registry."""
        registry: dict[str, tuple[str, str]] = {}
        cfg = load_config()
        chat_cfg = cfg.chat
        if chat_cfg and chat_cfg.mcp_tools_enabled is False:
            return registry

        selected = list(cfg.servers.keys())
        if chat_cfg and chat_cfg.mcp_servers:
            selected = [s for s in chat_cfg.mcp_servers if s in cfg.servers]

        for name in selected:
            try:
                server = cfg.servers[name]
                info_list = await list_mcp_tools(server)
                for info in info_list:
                    tname = info.get("name") or "tool"
                    oname = f"mcp.{name}.{tname}"
                    registry[oname] = (name, tname)
            except Exception:
                pass
        return registry

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        mcp_registry: dict[str, tuple[str, str]],
        cfg,
        session: ACPSession,
    ) -> str:
        """Execute a tool and return result."""
        # Try to use client fs capabilities if available
        if tool_name == "read_file" and self._has_client_capability("fs", "readTextFile"):
            return await self._read_file_via_client(session, args.get("path", ""))

        if tool_name == "write_file" and self._has_client_capability("fs", "writeTextFile"):
            return await self._write_file_via_client(session, args.get("path", ""), args.get("content", ""))

        if tool_name.startswith("mcp."):
            server_name, inner_name = mcp_registry.get(tool_name, (None, None))
            if server_name and inner_name:
                server = cfg.servers.get(server_name)
                if server:
                    mcp_resp = await call_mcp_tool(server, inner_name, args)
                    parts = []
                    for c in mcp_resp.get("content", []) or []:
                        if c.get("type") == "text":
                            parts.append(c.get("text", ""))
                    return "\n\n".join(parts) or json.dumps(mcp_resp, ensure_ascii=False)
            return f"Error: Unknown MCP tool {tool_name}"

        registry = get_tool_registry()
        result: ToolResult = registry.execute_tool(tool_name, **args)
        return result.content if result.success else f"Error: {result.error}"

    def _has_client_capability(self, category: str, capability: str) -> bool:
        """Check if client has a specific capability."""
        if not self._client_capabilities:
            return False
        if category == "fs":
            fs = getattr(self._client_capabilities, "fs", None)
            if fs:
                return getattr(fs, capability.replace("TextFile", "_text_file"), False)
        if category == "terminal":
            return getattr(self._client_capabilities, "terminal", False)
        return False

    async def _read_file_via_client(self, session: ACPSession, path: str) -> str:
        """Read file using client's fs capability."""
        if not self._conn:
            return "Error: No client connection"
        try:
            abs_path = path if os.path.isabs(path) else os.path.join(session.cwd, path)
            result = await self._conn.read_text_file(session_id=session.session_id, path=abs_path)
            return result.content
        except Exception as e:
            return f"Error reading file: {e}"

    async def _write_file_via_client(self, session: ACPSession, path: str, content: str) -> str:
        """Write file using client's fs capability."""
        if not self._conn:
            return "Error: No client connection"
        try:
            abs_path = path if os.path.isabs(path) else os.path.join(session.cwd, path)
            await self._conn.write_text_file(session_id=session.session_id, path=abs_path, content=content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    def _get_tool_kind(self, tool_name: str) -> str:
        """Get tool kind for ACP reporting."""
        kinds = {
            "read_file": "read",
            "write_file": "edit",
            "edit_file": "edit",
            "bash": "execute",
            "grep": "search",
            "think": "think",
        }
        return kinds.get(tool_name, "other")

    def _save_session(self, session: ACPSession) -> None:
        """Save session to file."""
        try:
            sessions_dir = Path.home() / ".config" / "amcp" / "acp_sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            session_file = sessions_dir / f"{session.session_id}.json"
            data = {
                "session_id": session.session_id,
                "cwd": session.cwd,
                "created_at": session.created_at,
                "current_mode_id": session.current_mode_id,
                "conversation_history": session.conversation_history,
                "tool_calls_history": session.tool_calls_history,
            }
            session_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


async def run_acp_agent(agent_spec: ResolvedAgentSpec | None = None) -> None:
    """Run the AMCP agent as an ACP server."""
    agent = AMCPAgent(agent_spec)
    await run_agent(agent)


def main() -> None:
    """Entry point for ACP agent."""
    asyncio.run(run_acp_agent())


if __name__ == "__main__":
    main()
