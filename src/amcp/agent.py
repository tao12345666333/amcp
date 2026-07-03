"""Agent execution engine with tool support, hooks, and MCP integration."""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.status import Status
from rich.text import Text

from .agent_spec import ResolvedAgentSpec, get_default_agent_spec
from .chat import _make_client, _resolve_api_key, _resolve_base_url
from .compaction import SmartCompactor, estimate_tokens
from .config import AMCPConfig, ContextConfig, load_config
from .hooks import (
    HookDecision,
    run_post_tool_use_hooks,
    run_pre_tool_use_hooks,
    run_user_prompt_hooks,
)
from .mcp_client import call_mcp_tool, list_mcp_tools
from .memory import get_memory_manager
from .memory_review import MEMORY_GUIDANCE, run_memory_review
from .message_queue import MessagePriority, get_message_queue_manager
from .multi_agent import AgentConfig
from .progressive.context_budget import ContextBudget, ContextBudgetManager, estimate_text_tokens
from .progressive.relevance import RelevanceScorer
from .progressive.skill_view import ProgressiveSkillView
from .progressive.tool_view import ProgressiveToolView
from .progressive.usage_tracker import ToolUsageTracker
from .project_rules import ProjectRulesLoader
from .skills import get_skill_manager
from .tools import ToolRegistry
from .ui import LiveUI

logger = logging.getLogger(__name__)


class AgentExecutionError(Exception):
    """Raised when agent execution fails."""

    pass


class MaxStepsReached(Exception):
    """Raised when agent reaches maximum execution steps."""

    pass


class BusyError(Exception):
    """Raised when agent session is busy processing another request."""

    pass


class Agent:
    """
    Enhanced agent execution engine with tool calling and conversation management.

    Features:
    - Context management with compression
    - Tool execution tracking and limits
    - Error handling and retries
    - Status reporting and progress indication
    - Conversation history persistence
    - Project rules loading from AGENTS.md
    - Event callbacks for real-time monitoring
    """

    def __init__(self, agent_spec: ResolvedAgentSpec | None = None, session_id: str | None = None):
        self.agent_spec = agent_spec or get_default_agent_spec()
        self.console = Console()
        self.tool_registry = ToolRegistry()
        self.execution_context: dict[str, Any] = {}
        self.step_count = 0
        self.tool_calls_history: list[dict[str, Any]] = []

        # Conversation history management
        self.session_id = session_id or self._generate_session_id()
        self.conversation_history: list[dict[str, Any]] = []
        self.session_file = Path.home() / ".config" / "amcp" / "sessions" / f"{self.session_id}.json"

        # Tool call tracking for per-conversation and per-session limits
        self.current_conversation_tool_calls: list[dict[str, Any]] = []

        # Per-request tracking (reset on each new request)
        self.current_request_tool_calls: int = 0  # Tools called in current request
        self.current_request_llm_calls: int = 0  # LLM calls in current request

        # Session-level cumulative tracking
        self.total_llm_calls: int = 0  # Total LLM calls across entire session

        # Project rules loader (will be initialized with work_dir during run)
        self._project_rules_loader: ProjectRulesLoader | None = None

        # Event callbacks for real-time monitoring (used by server)
        self._event_callbacks: list[Callable[[str, dict[str, Any]], None]] = []

        # Progressive context selection components
        self._relevance_scorer = RelevanceScorer()
        self._progressive_tool_view = ProgressiveToolView(self._relevance_scorer)
        self._progressive_skill_view = ProgressiveSkillView(self._relevance_scorer)

        # Load existing conversation history if available
        self._load_conversation_history()

        # If this is a new session (no existing history), reset the current conversation counter
        if not self.conversation_history:
            self._reset_current_conversation_tool_calls()

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return str(uuid.uuid4())[:8]

    def _ensure_sessions_dir(self) -> None:
        """Ensure sessions directory exists."""
        sessions_dir = self.session_file.parent
        sessions_dir.mkdir(parents=True, exist_ok=True)

    def _load_conversation_history(self) -> None:
        """Load conversation history from session file."""
        try:
            if self.session_file.exists():
                self._ensure_sessions_dir()
                with open(self.session_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self.conversation_history = data.get("conversation_history", [])
                    self.tool_calls_history = data.get("tool_calls_history", [])
                    self.current_conversation_tool_calls = data.get("current_conversation_tool_calls", [])
                    self.total_llm_calls = data.get("total_llm_calls", 0)
                    self.console.print(
                        f"[dim]Loaded conversation history: {len(self.conversation_history)} messages, {len(self.tool_calls_history)} total tool calls[/dim]"
                    )
        except (OSError, json.JSONDecodeError) as e:
            self.console.print(f"[yellow]Warning: Could not load conversation history: {e}[/yellow]")
            self.conversation_history = []
            self.tool_calls_history = []
            self.total_llm_calls = 0

    def _save_conversation_history(self) -> None:
        """Save conversation history to session file."""
        try:
            self._ensure_sessions_dir()
            data = {
                "session_id": self.session_id,
                "agent_name": self.name,
                "created_at": datetime.now().isoformat(),
                "conversation_history": self.conversation_history,
                "tool_calls_history": self.tool_calls_history,
                "current_conversation_tool_calls": self.current_conversation_tool_calls,
                "total_llm_calls": self.total_llm_calls,
            }
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            self.console.print(f"[yellow]Warning: Could not save conversation history: {e}[/yellow]")

    def clear_conversation_history(self) -> None:
        """Clear conversation history and delete session file."""
        self.conversation_history = []
        self.tool_calls_history = []
        self.current_conversation_tool_calls = []
        self.total_llm_calls = 0
        self.current_request_llm_calls = 0
        self.current_request_tool_calls = 0
        try:
            if self.session_file.exists():
                self.session_file.unlink()
        except OSError as e:
            self.console.print(f"[yellow]Warning: Could not delete session file: {e}[/yellow]")

    def get_conversation_summary(self) -> dict[str, Any]:
        """Get summary of the conversation (session-level statistics)."""
        return {
            "session_id": self.session_id,
            "agent_name": self.name,
            "message_count": len(self.conversation_history),
            "total_tool_calls": len(self.tool_calls_history),  # Session total
            "total_llm_calls": self.total_llm_calls,  # Session total
            "session_file": str(self.session_file),
        }

    @property
    def name(self) -> str:
        return self.agent_spec.name

    @property
    def max_steps(self) -> int:
        return self.agent_spec.max_steps

    def add_event_callback(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """Register an event callback for real-time monitoring.

        Args:
            callback: Function that receives (event_type, event_data)
        """
        self._event_callbacks.append(callback)

    def remove_event_callback(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """Remove an event callback.

        Args:
            callback: The callback to remove
        """
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to all registered callbacks.

        Args:
            event_type: Type of event (e.g., 'tool.call_start', 'tool.call_complete')
            data: Event data
        """
        event_data = {
            "session_id": self.session_id,
            "agent_name": self.name,
            "timestamp": datetime.now().isoformat(),
            **data,
        }
        for callback in self._event_callbacks:
            with contextlib.suppress(Exception):
                callback(event_type, event_data)

    def _resolve_context_config(self) -> ContextConfig:
        """Load context config with defaults."""
        cfg = load_config()
        return cfg.context or ContextConfig()

    def _resolve_model_name(self, cfg: AMCPConfig | None = None) -> str:
        """Resolve model name used for budget and token decisions."""
        resolved_cfg = cfg or load_config()
        if self.agent_spec.model:
            return self.agent_spec.model
        if resolved_cfg.chat and resolved_cfg.chat.model:
            return resolved_cfg.chat.model
        return "DeepSeek-V3.1-Terminus"

    def _calculate_context_budget(self, conversation_tokens: int, model_name: str | None = None) -> ContextBudget:
        """Calculate context budget for current request."""
        context_cfg = self._resolve_context_config()
        model = model_name or self._resolve_model_name()
        manager = ContextBudgetManager(model=model, config=context_cfg)
        return manager.calculate_budget(conversation_tokens)

    def _trim_to_token_budget(self, text: str, token_budget: int) -> str:
        """Trim long text to token budget using a stable head/tail strategy."""
        if token_budget <= 0 or not text:
            return ""

        current_tokens = estimate_text_tokens(text)
        if current_tokens <= token_budget:
            return text

        char_budget = max(token_budget * 4, 200)
        if len(text) <= char_budget:
            return text

        head_chars = int(char_budget * 0.7)
        tail_chars = max(char_budget - head_chars, 0)
        if tail_chars > 0:
            return (
                text[:head_chars].rstrip()
                + "\n\n[... trimmed for context budget ...]\n\n"
                + text[-tail_chars:].lstrip()
            )
        return text[:char_budget].rstrip() + "\n\n[... trimmed for context budget ...]"

    def _get_system_prompt(self, work_dir: Path | None = None, user_input: str = "") -> str:
        """Get resolved system prompt with template variables and project rules."""
        current_time = datetime.now().isoformat()
        resolved_work_dir = work_dir.resolve() if work_dir else Path.cwd()
        work_dir_str = str(resolved_work_dir)
        cfg = load_config()
        context_cfg = cfg.context or ContextConfig()
        model_name = self._resolve_model_name(cfg)

        conversation_tokens = estimate_tokens(self.conversation_history)
        budget = self._calculate_context_budget(conversation_tokens, model_name=model_name)

        # Note: MCP tools info will be loaded asynchronously during execution
        mcp_tools_info: list[dict[str, Any]] = []

        prompt_vars = {
            "work_dir": work_dir_str,
            "current_time": current_time,
            "agent_name": self.agent_spec.name,
            "mcp_tools": json.dumps(mcp_tools_info, indent=2),
        }

        # Build base system prompt
        try:
            base_prompt = self.agent_spec.system_prompt.format(**prompt_vars)
        except KeyError as e:
            self.console.print(f"[yellow]Warning: Missing template variable {e}[/yellow]")
            base_prompt = self.agent_spec.system_prompt

        # Load project rules from AGENTS.md files
        project_rules = self._load_project_rules(resolved_work_dir)

        # Get skills information
        skill_manager = get_skill_manager()

        # Ensure skills are discovered (includes built-in skills)
        if not skill_manager.get_all_skills():
            skill_manager.discover_skills(resolved_work_dir)

        # Build skills context
        skills_summary = ""
        skills_content = ""
        if context_cfg.progressive_skills:
            skill_result = self._progressive_skill_view.build_prompt(
                skills=skill_manager.get_skills(),
                user_input=user_input,
                active_skills={s.name for s in skill_manager.get_active_skills()},
                budget_tokens=budget.skills,
                relevance_threshold=context_cfg.skill_relevance_threshold,
            )
            skills_summary = skill_result.prompt
        else:
            skills_summary = skill_manager.build_skills_summary()
            skills_content = skill_manager.get_active_skills_content()

        # Get persona and memory context
        memory_manager = get_memory_manager(resolved_work_dir)
        persona_context = memory_manager.get_persona_context()
        memory_context = memory_manager.get_memory_context()

        # Respect per-component budgets for noisy sections
        if project_rules:
            project_rules = self._trim_to_token_budget(project_rules, budget.rules)
        if persona_context:
            persona_context = self._trim_to_token_budget(persona_context, max(500, budget.memory))
        if memory_context:
            memory_context = self._trim_to_token_budget(memory_context, budget.memory)

        # Combine all parts
        combined_prompt = base_prompt
        if persona_context:
            combined_prompt = persona_context + "\n\n" + combined_prompt
        if project_rules:
            combined_prompt += "\n\n" + project_rules
        combined_prompt += "\n\n" + MEMORY_GUIDANCE
        if skills_summary:
            combined_prompt += "\n\n" + skills_summary
        if memory_context:
            combined_prompt += "\n\n" + memory_context
        if skills_content:
            combined_prompt += "\n\n" + skills_content

        self._emit_event(
            "context.budget_allocated",
            {
                "model": model_name,
                "conversation_tokens": conversation_tokens,
                "prompt_budget": budget.prompt_budget,
                "tools_budget": budget.tools,
                "skills_budget": budget.skills,
                "memory_budget": budget.memory,
                "rules_budget": budget.rules,
            },
        )

        return combined_prompt

    def _load_project_rules(self, work_dir: Path) -> str:
        """Load project rules from AGENTS.md files.

        Args:
            work_dir: Working directory to search from

        Returns:
            Combined project rules content or empty string
        """
        # Initialize or update the project rules loader
        if self._project_rules_loader is None or self._project_rules_loader.work_dir != work_dir:
            self._project_rules_loader = ProjectRulesLoader(work_dir)

        rules = self._project_rules_loader.load_rules()

        # Log loaded files
        if rules:
            loaded_files = self._project_rules_loader.get_loaded_files()
            if loaded_files:
                file_names = [f.name for f in loaded_files]
                self.console.print(f"[dim]📋 Loaded project rules: {', '.join(file_names)}[/dim]")

        return rules

    def get_project_rules_info(self) -> dict[str, Any]:
        """Get information about loaded project rules.

        Returns:
            Dictionary with rules information
        """
        if self._project_rules_loader:
            return self._project_rules_loader.get_rules_summary()
        return {"has_rules": False, "files_loaded": []}

    async def _get_mcp_tools_info(self, cfg: AMCPConfig) -> list[dict[str, Any]]:
        """Get information about available MCP tools."""
        tools_info = []

        for server_name, server in cfg.servers.items():
            try:
                tools = await list_mcp_tools(server)
                for tool in tools:
                    tools_info.append(
                        {
                            "name": f"mcp.{server_name}.{tool['name']}",
                            "description": tool.get("description", ""),
                            "server": server_name,
                        }
                    )
            except (OSError, ValueError, KeyError) as e:
                self.console.print(f"[yellow]Warning: Could not load tools from {server_name}: {e}[/yellow]")

        return tools_info

    def _should_limit_tool_calls(self, tool_name: str) -> bool:
        """Check if a tool should be limited to prevent infinite loops."""
        # Per-tool limits (each tool tracked separately)
        current_conversation_calls = sum(
            1 for call in self.current_conversation_tool_calls if call.get("tool") == tool_name
        )

        # read_file: 100 per conversation, 600 per session
        if tool_name == "read_file":
            if current_conversation_calls >= 100:
                self.console.print("[yellow]Per-conversation read_file limit reached (100 calls)[/yellow]")
                return True

            total_session_calls = sum(1 for call in self.tool_calls_history if call.get("tool") == "read_file")
            if total_session_calls >= 600:
                self.console.print("[yellow]Per-session read_file limit reached (600 calls)[/yellow]")
                return True
            return False

        # MCP tools: 100 per tool per conversation
        return tool_name.startswith("mcp.") and current_conversation_calls >= 100

    def _reset_current_conversation_tool_calls(self) -> None:
        """Reset the current conversation tool calls counter for a new conversation."""
        self.current_conversation_tool_calls = []

    def _add_execution_context(self, key: str, value: Any) -> None:
        """Add context information for tool execution."""
        self.execution_context[key] = value

    def _get_context_vars(self) -> dict[str, str]:
        """Get context variables for system prompt."""
        return {
            "step_count": str(self.step_count),
            "max_steps": str(self.max_steps),
            "tools_called": str(len(self.tool_calls_history)),
            "work_dir": str(Path.cwd()),
        }

    async def run(
        self,
        user_input: str,
        work_dir: Path | None = None,
        stream: bool = True,
        show_progress: bool = True,
        priority: MessagePriority = MessagePriority.NORMAL,
        queue_if_busy: bool = True,
    ) -> str:
        """
        Run the agent with the given user input.

        Args:
            user_input: User's request
            work_dir: Working directory for context
            stream: Whether to stream responses
            show_progress: Whether to show progress indicators
            priority: Message priority (for queuing)
            queue_if_busy: Whether to queue the message if session is busy

        Returns:
            Agent's response

        Raises:
            AgentExecutionError: If execution fails
            MaxStepsReached: If max steps exceeded
            BusyError: If session is busy and queue_if_busy is False
        """
        queue_manager = get_message_queue_manager()

        # Check if session is busy
        if queue_manager.is_busy(self.session_id):
            if queue_if_busy:
                # Queue the message for later processing
                await queue_manager.enqueue(
                    session_id=self.session_id,
                    prompt=user_input,
                    priority=priority,
                    work_dir=str(work_dir) if work_dir else None,
                    stream=stream,
                    show_progress=show_progress,
                )
                self.console.print(
                    f"[dim]Message queued ({queue_manager.queued_count(self.session_id)} in queue)[/dim]"
                )
                return "[Message queued for later processing]"
            else:
                raise BusyError(f"Session {self.session_id} is busy processing another request")

        # Acquire session lock
        acquired = await queue_manager.acquire(self.session_id)
        if not acquired:
            # Race condition - queue it
            if queue_if_busy:
                await queue_manager.enqueue(
                    session_id=self.session_id,
                    prompt=user_input,
                    priority=priority,
                )
                return "[Message queued for later processing]"
            else:
                raise BusyError(f"Session {self.session_id} is busy processing another request")

        try:
            # Process the current message
            result = await self._process_message(user_input, work_dir, stream, show_progress)

            # Process any queued messages
            while True:
                next_msg = await queue_manager.dequeue(self.session_id)
                if not next_msg:
                    break

                # Process queued message
                self.console.print("[dim]Processing queued message...[/dim]")
                queued_work_dir = Path(next_msg.metadata["work_dir"]) if next_msg.metadata.get("work_dir") else work_dir
                await self._process_message(
                    next_msg.prompt,
                    queued_work_dir,
                    next_msg.metadata.get("stream", stream),
                    next_msg.metadata.get("show_progress", show_progress),
                )

            return result

        finally:
            # Always release the session lock
            queue_manager.release(self.session_id)

    async def _process_message(self, user_input: str, work_dir: Path | None, stream: bool, show_progress: bool) -> str:
        """
        Process a single message (internal implementation).

        This is the core message processing logic, extracted from run()
        to support queue-based processing.
        """
        # Run UserPromptSubmit hooks
        prompt_hook_output = await run_user_prompt_hooks(
            session_id=self.session_id,
            prompt=user_input,
            project_dir=work_dir,
        )

        # Check if hook denied the prompt
        if not prompt_hook_output.continue_execution:
            if prompt_hook_output.stop_reason:
                self.console.print(f"[yellow]Prompt blocked: {prompt_hook_output.stop_reason}[/yellow]")
            return prompt_hook_output.stop_reason or "Prompt blocked by hook"

        # Show hook feedback if any
        if prompt_hook_output.feedback:
            self.console.print(f"[dim]Hook: {prompt_hook_output.feedback}[/dim]")

        # Save user input to conversation history immediately to preserve context
        self.conversation_history.append({"role": "user", "content": user_input})

        try:
            with self._create_progress_context(show_progress) as status:
                status.update(f"[bold]Agent {self.name}[/bold] thinking...")

                # Prepare messages with conversation history
                system_prompt = self._get_system_prompt(work_dir, user_input=user_input)
                messages = [{"role": "system", "content": system_prompt}]

                # Add conversation history with compaction if needed
                history_to_add = list(self.conversation_history)

                # Apply compaction if context is too large
                cfg = load_config()
                base_url = _resolve_base_url(self.agent_spec.base_url or None, cfg.chat)
                api_key = _resolve_api_key(None, cfg.chat)
                client = _make_client(base_url, api_key)
                model = cfg.chat.model if cfg.chat and cfg.chat.model else "DeepSeek-V3.1-Terminus"
                compactor = SmartCompactor(client, model)

                if compactor.should_compact(history_to_add):
                    # Pre-compaction memory flush: save durable memories before
                    # context is summarized (inspired by openclaw's memory flush).
                    status.update(f"[bold]Agent {self.name}[/bold] saving memories before compaction...")
                    await self._run_memory_review(
                        conversation_snapshot=history_to_add,
                        system_prompt=system_prompt,
                        tools=None,  # will be built below
                        work_dir=work_dir,
                        status=status,
                    )

                    status.update(f"[bold]Agent {self.name}[/bold] compacting context...")
                    history_to_add, _ = compactor.compact(history_to_add)
                    self.console.print("[dim]Context compacted to reduce token usage[/dim]")

                messages.extend(history_to_add)

                # Build tools and registry (combined to avoid duplicate MCP calls)
                tools, tool_registry = await self._build_tools_and_registry(
                    user_input=user_input,
                    conversation_history=history_to_add,
                )

                # Run chat with tools
                result = await self._run_with_tools(
                    messages=messages, tools=tools, tool_registry=tool_registry, stream=stream, status=status
                )

                # Save assistant response
                self.conversation_history.append({"role": "assistant", "content": result})

                # Save to file
                self._save_conversation_history()

                # Log to memory history
                try:
                    memory_mgr = get_memory_manager(work_dir)
                    summary = f"User: {user_input[:200]}\nAgent: {result[:300]}"
                    memory_mgr.append_history(
                        content=summary,
                        session_id=self.session_id,
                        tags=["conversation"],
                        scope="project" if work_dir else "user",
                    )
                except (OSError, ValueError):
                    pass  # Memory logging is best-effort

                return result

        except AgentExecutionError:
            raise
        except Exception as e:
            # Save error information to conversation history to maintain context
            error_msg = f"Agent execution failed: {e}"
            self.conversation_history.append({"role": "assistant", "content": f"[Error] {error_msg}"})

            # Save conversation history even on failure to preserve context
            self._save_conversation_history()

            self.console.print(Text.assemble(("Agent execution failed: ", "red"), str(e)))
            raise AgentExecutionError(f"Agent execution failed: {e}") from e

    async def _run_memory_review(
        self,
        conversation_snapshot: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]] | None,
        work_dir: Path | None,
        status: Any = None,
    ) -> None:
        """Run a pre-compaction memory flush to save durable memories.

        Inspired by openclaw's pre-compaction memory flush: before the
        conversation context is summarized/compacted, give the agent one
        chance to save important user preferences, facts, and identity
        details to persistent memory.  Failures are silently ignored.
        """
        try:
            cfg = load_config()
            base_url = _resolve_base_url(self.agent_spec.base_url or None, cfg.chat)
            api_key = _resolve_api_key(None, cfg.chat)
            client = _make_client(base_url, api_key)
            model = cfg.chat.model if cfg.chat and cfg.chat.model else "DeepSeek-V3.1-Terminus"

            # Build memory-only tool list from the global registry
            from .tools import get_tool_registry

            registry = get_tool_registry()
            memory_tool = registry.get_tool("memory")
            if not memory_tool:
                return
            memory_tools = [memory_tool.get_spec()]

            self._emit_event("memory.review_start", {})

            result = await run_memory_review(
                client=client,
                model=model,
                system_prompt=system_prompt,
                conversation_snapshot=conversation_snapshot,
                tools=memory_tools,
                tool_registry=registry,
            )

            self._emit_event(
                "memory.review_complete",
                {"saved": result != "Nothing to save." if result else False},
            )

            if result and result.strip() != "Nothing to save.":
                self.console.print("[dim]Memory flush: saved durable memories before compaction[/dim]")
            else:
                logger.debug("Memory flush: nothing to save")

        except Exception as e:
            logger.debug(f"Memory flush failed (non-critical): {e}")

    def is_busy(self) -> bool:
        """Check if this agent's session is currently busy."""
        return get_message_queue_manager().is_busy(self.session_id)

    def queued_count(self) -> int:
        """Get the number of queued messages for this session."""
        return get_message_queue_manager().queued_count(self.session_id)

    def queued_prompts(self) -> list[str]:
        """Get list of queued prompts for this session."""
        return get_message_queue_manager().queued_prompts(self.session_id)

    async def clear_queue(self) -> int:
        """Clear all queued messages for this session."""
        return await get_message_queue_manager().clear_queue(self.session_id)

    def get_queue_status(self) -> dict[str, Any]:
        """Get queue status for this session."""
        return get_message_queue_manager().get_queue_status(self.session_id)

    async def _build_tools_and_registry(
        self,
        user_input: str = "",
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
        """Build list of available tools and registry for MCP tool dispatch.

        Combined method to avoid duplicate MCP server calls.

        Returns:
            Tuple of (tools list, registry dict)
        """
        tools: list[dict[str, Any]] = []
        registry: dict[str, tuple[str, str]] = {}
        conversation = conversation_history or self.conversation_history

        # Add all built-in tools from registry
        from .tools import get_tool_registry

        allowed_tools = set(self.agent_spec.tools) if self.agent_spec.tools else None
        excluded_tools = set(self.agent_spec.exclude_tools or [])

        tool_registry = get_tool_registry()
        for tool_name in tool_registry.list_tools():
            if allowed_tools is not None and tool_name not in allowed_tools:
                continue
            if tool_name in excluded_tools:
                continue
            tool = tool_registry.get_tool(tool_name)
            if tool and hasattr(tool, "get_spec"):
                tools.append(tool.get_spec())

        # Load MCP tools
        cfg = load_config()
        chat_cfg = cfg.chat

        # Decide which servers to include
        if chat_cfg and chat_cfg.mcp_tools_enabled is False:
            selected = []
        elif chat_cfg and chat_cfg.mcp_servers:
            selected = [s for s in chat_cfg.mcp_servers if s in cfg.servers]
        else:
            selected = list(cfg.servers.keys())

        # Load MCP tools asynchronously (single call per server)
        for name in selected:
            try:
                server = cfg.servers[name]
                info_list = await list_mcp_tools(server)
                for info in info_list:
                    tname = info.get("name") or "tool"
                    oname = f"mcp.{name}.{tname}"
                    if allowed_tools is not None and oname not in allowed_tools:
                        continue
                    if oname in excluded_tools:
                        continue
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
                    # Also add to registry
                    registry[oname] = (name, tname)
            except (OSError, ValueError, KeyError) as e:
                self.console.print(f"[yellow]MCP tool discovery failed for server {name}:[/yellow] {e}")

        context_cfg = cfg.context or ContextConfig()
        if not context_cfg.progressive_tools:
            return tools, registry

        conversation_tokens = estimate_tokens(conversation)
        budget = self._calculate_context_budget(conversation_tokens)
        usage_snapshot = ToolUsageTracker.from_history(self.tool_calls_history)

        selection = self._progressive_tool_view.select_tools(
            tools=tools,
            user_input=user_input,
            conversation=conversation,
            usage=usage_snapshot,
            budget_tokens=budget.tools,
            relevance_threshold=context_cfg.tool_relevance_threshold,
            tier_overrides=context_cfg.tool_tiers,
        )

        selected_tools = selection.selected_tools
        selected_names = {
            tool.get("function", {}).get("name", "") for tool in selected_tools if tool.get("function", {}).get("name")
        }
        filtered_registry = {name: ref for name, ref in registry.items() if name in selected_names}

        self._emit_event(
            "context.tools_filtered",
            {
                "selected_count": len(selected_tools),
                "total_count": len(tools),
                "hidden_count": selection.hidden_count,
                "excluded_tools": selection.excluded_tools,
            },
        )

        return selected_tools, filtered_registry

    def _get_read_file_tool_spec(self) -> dict[str, Any]:
        """Get read_file tool specification."""
        return {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a text file from the local workspace. Returns the full file content with line numbers. If no ranges specified, reads the entire file. CRITICAL: You MUST provide a path to a specific FILE, not a directory. Use relative paths from current working directory (e.g., 'src/amcp/readfile.py', 'README.md'), NOT absolute paths starting with '/'. COMMON FILES: 'src/amcp/readfile.py', 'src/amcp/rg.py', 'src/amcp/cli.py', 'src/amcp/chat.py', 'README.md', 'pyproject.toml'. NEVER use just 'src/amcp' - it's a directory, not a file. IMPORTANT: When you get the file content, analyze it and provide your response - don't call the tool again unless you need additional different files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to a specific FILE (not directory). Use relative paths like 'src/amcp/readfile.py', NEVER directories like 'src/amcp'. COMMON FILES: 'src/amcp/readfile.py', 'src/amcp/rg.py', 'src/amcp/cli.py', 'src/amcp/chat.py', 'README.md', 'pyproject.toml'. Always include the file extension (.py, .md, .toml, etc).",
                        },
                        "ranges": {
                            "type": "array",
                            "items": {"type": "string", "pattern": "^\\d+-\\d+$"},
                            "description": "Optional list of line ranges like '1-200'. Use only if you need specific line ranges. For general file analysis, omit this to get the full file.",
                        },
                        "max_lines": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5000,
                            "description": "Safety cap for lines returned per block (default 400)",
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        }

    async def _run_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_registry: dict[str, Any],
        stream: bool,
        status: Status,
    ) -> str:
        """Run chat with tools and enhanced tracking."""
        cfg = load_config()

        # Use new LLM client abstraction
        from .llm import create_llm_client

        llm_client = create_llm_client(cfg.chat)

        # Override model if specified in agent spec
        if self.agent_spec.model:
            llm_client.model = self.agent_spec.model

        # Override the chat function to add our tracking
        return await self._enhanced_chat_with_tools(
            llm_client=llm_client,
            messages=messages,
            tools=tools,
            tool_registry=tool_registry,
            stream=stream,
            status=status,
        )

    async def _enhanced_chat_with_tools(
        self,
        llm_client,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_registry: dict[str, Any],
        stream: bool,
        status: Status,
        max_steps: int | None = None,
    ) -> str:
        """Enhanced version of _chat_with_tools with better tracking."""
        max_steps = max_steps or self.max_steps

        # Reset per-request counters at the start of each request
        self.current_request_tool_calls = 0
        self.current_request_llm_calls = 0

        # Create a working copy of messages
        messages = list(messages)
        used_tools = False

        for step in range(max_steps):
            self.step_count = step + 1
            # Update LLM call counters (both per-request and session total)
            self.current_request_llm_calls += 1
            self.total_llm_calls += 1
            status.update(f"[bold]Agent {self.name}[/bold] - LLM Call {self.current_request_llm_calls}")

            # Define stream callback if streaming is enabled
            stream_callback = None
            if stream:

                def _stream_callback(chunk: str):
                    self._emit_event("message.chunk", {"content": chunk})

                stream_callback = _stream_callback

            resp = llm_client.chat(messages=messages, tools=tools, stream_callback=stream_callback)

            if resp.tool_calls:
                tool_calls = resp.tool_calls
                used_tools = True
                status.update(f"[bold]Agent {self.name}[/bold] - Executing {len(tool_calls)} tool(s)...")

                # Check if any tool should be limited before processing
                limited_tools = []
                for tc in tool_calls:
                    tool_name = tc["name"]
                    if self._should_limit_tool_calls(tool_name):
                        limited_tools.append(tool_name)

                if limited_tools:
                    status.update(
                        f"[bold]Agent {self.name}[/bold] - Tools {limited_tools} limited, forcing response..."
                    )
                    self.console.print(f"[yellow]Tools {limited_tools} limited, forcing response[/yellow]")
                    # Add system message to force response
                    messages.append(
                        {
                            "role": "system",
                            "content": f"You have already called the following tools too many times: {', '.join(limited_tools)}. Please analyze the information you have and provide your response without calling these tools again.",
                        }
                    )
                    # Get a final response from the LLM with the current messages
                    try:
                        final_resp = llm_client.chat(messages=messages)
                        final_text = final_resp.content or ""
                        status.update(f"[bold]Agent {self.name}[/bold] - ✅ Complete")
                        return final_text
                    except Exception as e:
                        status.update(f"[bold]Agent {self.name}[/bold] - ⚠️ Error getting final response")
                        return f"Error: Could not get final response: {e}"

                # Process tool calls with Live UI
                with LiveUI() as live_ui:
                    for tc in tool_calls:
                        tool_name = tc["name"]
                        tool_id = tc["id"]
                        args = json.loads(tc["arguments"] or "{}")

                        # Run PreToolUse hooks
                        pre_hook_output = await run_pre_tool_use_hooks(
                            session_id=self.session_id,
                            tool_name=tool_name,
                            tool_input=args,
                            tool_use_id=tool_id,
                        )

                        # Check hook decision
                        if pre_hook_output.decision == HookDecision.DENY:
                            # Tool execution denied by hook
                            tool_result_text = (
                                f"Tool denied by hook: {pre_hook_output.decision_reason or 'No reason given'}"
                            )
                            block = live_ui.add_tool(tool_name, args)
                            live_ui.finish_tool(block, success=False, result=tool_result_text)
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_name,
                                    "content": tool_result_text,
                                }
                            )
                            continue

                        # Apply any input updates from hooks
                        if pre_hook_output.updated_input:
                            args = {**args, **pre_hook_output.updated_input}

                        # Record tool call
                        tool_call_record = {
                            "step": self.step_count,
                            "tool": tool_name,
                            "args": tc["arguments"],
                            "timestamp": datetime.now().isoformat(),
                        }
                        self.tool_calls_history.append(tool_call_record)
                        self.current_conversation_tool_calls.append(tool_call_record)
                        self.current_request_tool_calls += 1  # Track per-request tool calls

                        # Add tool block to UI
                        block = live_ui.add_tool(tool_name, args)

                        # Emit tool call start event
                        self._emit_event(
                            "tool.call_start",
                            {
                                "tool_name": tool_name,
                                "tool_id": tool_id,
                                "arguments": args,
                                "step": self.step_count,
                            },
                        )

                        # Track execution time
                        tool_start_time = time.time()

                        # Execute tool
                        try:
                            cfg = load_config()
                            tool_response_data = {}  # For hook output

                            if tool_name.startswith("mcp."):
                                # Handle MCP tools
                                server_name, inner_name = tool_registry.get(tool_name, (None, None))
                                if server_name and inner_name:
                                    server = cfg.servers.get(server_name)
                                    if server:
                                        mcp_resp = await call_mcp_tool(server, inner_name, args)
                                        tool_response_data = mcp_resp
                                        parts = []
                                        for c in mcp_resp.get("content", []) or []:
                                            if c.get("type") == "text":
                                                parts.append(c.get("text", ""))
                                        tool_result_text = "\n\n".join(parts) or json.dumps(
                                            mcp_resp, ensure_ascii=False
                                        )
                                        live_ui.finish_tool(block, success=True, result=tool_result_text)
                                    else:
                                        tool_result_text = f"Error: Unknown MCP server {server_name}"
                                        tool_response_data = {"error": tool_result_text}
                                        live_ui.finish_tool(block, success=False, result=tool_result_text)
                                else:
                                    tool_result_text = f"Error: Unknown MCP tool {tool_name}"
                                    tool_response_data = {"error": tool_result_text}
                                    live_ui.finish_tool(block, success=False, result=tool_result_text)
                            else:
                                # Handle built-in tools
                                from .tools import get_tool_registry

                                registry = get_tool_registry()
                                tool_result = registry.execute_tool(tool_name, **args)

                                if tool_result.success:
                                    tool_result_text = tool_result.content
                                    tool_response_data = {"success": True, "content": tool_result_text}
                                    live_ui.finish_tool(block, success=True, result=tool_result_text)
                                else:
                                    tool_result_text = f"Error: {tool_result.error}"
                                    tool_response_data = {"success": False, "error": tool_result.error}
                                    live_ui.finish_tool(block, success=False, result=tool_result_text)

                            # Run PostToolUse hooks
                            post_hook_output = await run_post_tool_use_hooks(
                                session_id=self.session_id,
                                tool_name=tool_name,
                                tool_input=args,
                                tool_response=tool_response_data,
                                tool_use_id=tool_id,
                            )

                            # Apply any response updates from hooks
                            if post_hook_output.updated_response:
                                tool_result_text = json.dumps(post_hook_output.updated_response, ensure_ascii=False)

                            # Add hook feedback if any
                            if post_hook_output.feedback:
                                tool_result_text += f"\n\n[Hook feedback: {post_hook_output.feedback}]"

                            # Calculate execution duration
                            tool_duration_ms = (time.time() - tool_start_time) * 1000

                            # Emit tool call complete event
                            tool_success = (
                                tool_response_data.get("success", True)
                                if isinstance(tool_response_data, dict)
                                else True
                            )
                            self._emit_event(
                                "tool.call_complete",
                                {
                                    "tool_name": tool_name,
                                    "tool_id": tool_id,
                                    "success": tool_success,
                                    "duration_ms": tool_duration_ms,
                                    "result_length": len(tool_result_text),
                                },
                            )

                            # Add tool result to messages (truncate large results)
                            MAX_TOOL_RESULT_LEN = 8000
                            truncated_result = tool_result_text
                            if len(tool_result_text) > MAX_TOOL_RESULT_LEN:
                                truncated_result = tool_result_text[:MAX_TOOL_RESULT_LEN] + "\n... [truncated]"

                            messages.append(
                                {
                                    "role": "assistant",
                                    "content": resp.content or "",
                                    "tool_calls": [
                                        {
                                            "id": tool_id,
                                            "type": "function",
                                            "function": {"name": tool_name, "arguments": tc["arguments"] or "{}"},
                                        }
                                    ],
                                }
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_name,
                                    "content": truncated_result,
                                }
                            )

                        except Exception as e:
                            error_msg = f"Tool {tool_name} error: {type(e).__name__}: {e}"
                            live_ui.finish_tool(block, success=False, result=error_msg)

                            # Calculate execution duration
                            tool_duration_ms = (time.time() - tool_start_time) * 1000

                            # Emit tool call error event
                            self._emit_event(
                                "tool.call_error",
                                {
                                    "tool_name": tool_name,
                                    "tool_id": tool_id,
                                    "success": False,
                                    "error": error_msg,
                                    "duration_ms": tool_duration_ms,
                                },
                            )

                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_name,
                                    "content": error_msg,
                                }
                            )

                continue
            else:
                # No tool calls, return the response
                final_text = resp.content or ""
                if stream and not used_tools:
                    # For streaming, we'll implement a simple version
                    pass

                status.update(f"[bold]Agent {self.name}[/bold] - ✅ Complete")
                return final_text

        # Max steps reached
        status.update(f"[bold]Agent {self.name}[/bold] - ⚠️ Max steps reached")
        raise MaxStepsReached(self.max_steps)

    def _create_progress_context(self, show_progress: bool):
        """Create progress display context."""
        if show_progress:
            return Status("[bold]Agent starting...[/bold]", console=self.console)
        else:
            # Return a null context manager for silent operation
            from contextlib import nullcontext

            class NullStatus:
                """Null status object that does nothing."""

                def update(self, *args, **kwargs):
                    pass

            return nullcontext(NullStatus())

    def get_execution_summary(self) -> dict[str, Any]:
        """Get summary of agent execution (per-request statistics)."""
        return {
            "agent_name": self.name,
            "agent_mode": self.agent_spec.mode.value,
            "llm_calls": self.current_request_llm_calls,  # LLM calls in this request
            "max_llm_calls": self.max_steps,  # Max LLM calls allowed per request
            "tools_called": self.current_request_tool_calls,  # Tools called in this request
            "context_vars": self._get_context_vars(),
            "can_delegate": self.agent_spec.can_delegate,
            "is_busy": self.is_busy(),
            "queued_count": self.queued_count(),
        }


# Factory functions for creating agents from multi-agent configurations


def create_agent_from_config(
    config: AgentConfig,
    session_id: str | None = None,
) -> Agent:
    """
    Create an Agent from an AgentConfig.

    This is the primary way to instantiate agents using the multi-agent system.

    Args:
        config: AgentConfig from the multi_agent module
        session_id: Optional session ID for conversation persistence

    Returns:
        Configured Agent instance
    """

    # Convert AgentConfig to ResolvedAgentSpec
    from .agent_spec import ResolvedAgentSpec

    spec = ResolvedAgentSpec(
        name=config.name,
        description=config.description,
        mode=config.mode,
        system_prompt=config.system_prompt,
        tools=config.tools,
        exclude_tools=config.excluded_tools,
        max_steps=config.max_steps,
        model="",  # Use default from config
        base_url="",  # Use default from config
        can_delegate=config.can_delegate,
    )

    return Agent(agent_spec=spec, session_id=session_id)


def create_agent_by_name(
    name: str,
    session_id: str | None = None,
) -> Agent:
    """
    Create an Agent by looking up its name in the registry.

    Args:
        name: Name of the agent in the registry (e.g., "coder", "explorer", "planner")
        session_id: Optional session ID for conversation persistence

    Returns:
        Configured Agent instance

    Raises:
        ValueError: If agent name is not found in registry
    """
    from .multi_agent import get_agent_config

    config = get_agent_config(name)
    if config is None:
        from .multi_agent import get_agent_registry

        available = get_agent_registry().list_agents()
        raise ValueError(f"Unknown agent: {name}. Available agents: {', '.join(available)}")

    return create_agent_from_config(config, session_id)


def create_subagent(
    parent_agent: Agent,
    task_description: str,
    tools: list[str] | None = None,
) -> Agent:
    """
    Create a subagent for a specific task.

    This creates a new agent that inherits the session from the parent
    but has a focused task and possibly restricted tools.

    Args:
        parent_agent: The parent agent creating this subagent
        task_description: Description of the task for the subagent
        tools: Optional list of tools for the subagent

    Returns:
        New Agent configured as a subagent

    Raises:
        ValueError: If parent agent cannot delegate
    """
    if not parent_agent.agent_spec.can_delegate:
        raise ValueError(f"Agent '{parent_agent.name}' cannot delegate to subagents")

    from .multi_agent import create_subagent_config

    config = create_subagent_config(
        parent_name=parent_agent.name,
        task_description=task_description,
        tools=tools,
    )

    # Create subagent with a new session (isolated from parent)
    return create_agent_from_config(config)


def list_available_agents() -> list[str]:
    """
    List all available agent names.

    Returns:
        List of agent names from the registry
    """
    from .multi_agent import get_agent_registry

    return get_agent_registry().list_agents()


def list_primary_agents() -> list[str]:
    """
    List all primary (main) agent names.

    Returns:
        List of primary agent names
    """
    from .multi_agent import get_agent_registry

    return get_agent_registry().list_primary_agents()


def list_subagent_types() -> list[str]:
    """
    List all available subagent types.

    Returns:
        List of subagent names
    """
    from .multi_agent import get_agent_registry

    return get_agent_registry().list_subagents()
