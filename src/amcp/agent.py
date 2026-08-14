"""Agent execution engine with tool support, hooks, and MCP integration."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
import uuid
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.status import Status
from rich.text import Text

from .agent_spec import ResolvedAgentSpec, get_default_agent_spec
from .compaction import (
    CompactionConfig,
    SmartCompactor,
    estimate_request_tokens,
    estimate_tokens,
    get_model_context_window,
)
from .config import AMCPConfig, ChatConfig, ContextConfig, ModelConfig, load_config
from .hooks import (
    HookDecision,
    run_post_tool_use_hooks,
    run_pre_tool_use_hooks,
    run_user_prompt_hooks,
)
from .llm import ContextOverflowError, ProviderError, classify_provider_error
from .mcp_client import list_mcp_tools
from .mcp_naming import is_mcp_tool_name, mcp_tool_name, unique_function_name
from .memory import get_memory_manager
from .memory_review import MEMORY_GUIDANCE, run_memory_review
from .message_queue import MessagePriority
from .multi_agent import AgentConfig
from .progressive.context_budget import ContextBudget, ContextBudgetManager, estimate_text_tokens
from .progressive.relevance import RelevanceScorer
from .progressive.skill_view import ProgressiveSkillView
from .progressive.tool_view import ProgressiveToolView
from .progressive.usage_tracker import ToolUsageTracker
from .project_rules import ProjectRulesLoader
from .runtime import CancellationResult, RuntimeClosedError, SessionRuntime, TurnCancelledError, TurnHandle, TurnRequest
from .session_search import get_transcript_store
from .session_state import CompactionCheckpoint, SessionState
from .session_store import SessionStore, SessionTimelineStore
from .skills import get_skill_manager
from .tool_execution import (
    ToolCallProtocolError,
    ToolCapability,
    ToolExecutionContext,
    ToolExecutor,
    normalize_tool_calls,
)
from .tools import ToolRegistry
from .ui import LiveUI

logger = logging.getLogger(__name__)

DEFAULT_BASH_TOOL_LIMIT = 100
MEMORY_REVIEW_TURN_INTERVAL = 10
MEMORY_LOG_USER_LIMIT = 1000
MEMORY_LOG_AGENT_LIMIT = 2000


class AgentExecutionError(Exception):
    """Raised when agent execution fails."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class MaxStepsReached(Exception):
    """Raised when agent reaches maximum execution steps."""

    pass


def _repair_tool_call_pairing(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure assistant tool_calls and tool results stay strictly paired.

    Gemini-family backends reject requests where a function-call turn is not
    followed by exactly one function-response part per call. History that
    passes through trimming or compaction can lose responses, so missing ones
    are synthesized and orphaned tool results are dropped.
    """
    repaired: list[dict[str, Any]] = []
    pending_ids: list[str] = []
    pending_names: dict[str, str] = {}

    def flush_pending() -> None:
        for call_id in pending_ids:
            tool_result: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "[Tool result unavailable: synthesized to keep tool-call history paired]",
            }
            # Strict providers reject an empty function name, so only carry the
            # name when the paired call actually reported one. Provider
            # extra_content (e.g. Gemini thought signatures) stays on the call.
            paired_name = pending_names.get(call_id)
            if paired_name:
                tool_result["name"] = paired_name
            repaired.append(tool_result)
        pending_ids.clear()
        pending_names.clear()

    for message in messages:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            flush_pending()
            repaired.append(message)
            for call in message["tool_calls"]:
                if not isinstance(call, dict):
                    continue
                call_id = call.get("id")
                if isinstance(call_id, str) and call_id:
                    pending_ids.append(call_id)
                    function = call.get("function")
                    if isinstance(function, dict) and isinstance(function.get("name"), str):
                        pending_names[call_id] = function["name"]
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if call_id in pending_ids:
                pending_ids.remove(call_id)
                repaired.append(message)
            # Orphaned tool results are dropped.
        else:
            flush_pending()
            repaired.append(message)
    flush_pending()
    return repaired


def _is_tool_call_pairing_error(error: Exception) -> bool:
    """Check whether an error is a provider-side tool-call pairing rejection."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).lower()
        if "function response parts" in text or ("function call" in text and "invalid_argument" in text):
            return True
        current = current.__cause__
    return False


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

    def __init__(
        self,
        agent_spec: ResolvedAgentSpec | None = None,
        session_id: str | None = None,
        *,
        ephemeral: bool = False,
    ):
        """Initialize an agent, optionally without automatic durable projections."""
        from .task import TaskManager

        self.agent_spec = agent_spec or get_default_agent_spec()
        self.ephemeral = ephemeral
        self.console = Console()
        self.tool_registry = ToolRegistry()
        self.execution_context: dict[str, Any] = {}
        self.step_count = 0
        self.tool_calls_history: list[dict[str, Any]] = []

        # Conversation history management
        self.session_id = session_id or self._generate_session_id()
        self._task_manager = TaskManager()
        self.conversation_history: list[dict[str, Any]] = []
        self._session_store = SessionStore(
            Path.home() / ".config" / "amcp" / "sessions",
            self.session_id,
        )
        self._timeline_store = SessionTimelineStore(
            self._session_store.root,
            self.session_id,
        )
        self.session_file = self._session_store.path
        self._session_state = SessionState(
            session_id=self.session_id,
            agent_name=self.name,
        )

        # Tool call tracking for per-conversation and per-session limits
        self.current_conversation_tool_calls: list[dict[str, Any]] = []

        # Per-request tracking (reset on each new request)
        self.current_request_tool_calls: int = 0  # Tools called in current request
        self.current_request_llm_calls: int = 0  # LLM calls in current request

        # Session-level cumulative tracking
        self.total_llm_calls: int = 0  # Total LLM calls across entire session
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cached_input_tokens: int = 0
        self.total_cache_write_input_tokens: int = 0
        self.usage_reported_llm_calls: int = 0
        self.estimated_input_llm_calls: int = 0
        self.last_context_tokens: int = 0
        self.last_context_window: int = 0
        self.last_output_tokens: int | None = None
        self.last_usage_from_api: bool = False
        self._last_memory_review_turn_count: int = 0
        self._frozen_memory_project_root: Path | None = None
        self._frozen_persona_context: str = ""
        self._frozen_memory_context: str = ""
        self._pending_memory_review_tasks: set[asyncio.Task[None]] = set()
        self._lifecycle_lock = asyncio.Lock()
        self._closed = False
        self._close_complete = False

        # Project rules loader (will be initialized with work_dir during run)
        self._project_rules_loader: ProjectRulesLoader | None = None

        # Event callbacks for real-time monitoring (used by server)
        self._event_callbacks: list[Callable[[str, dict[str, Any]], None]] = []

        # Progressive context selection components
        self._relevance_scorer = RelevanceScorer()
        self._progressive_tool_view = ProgressiveToolView(self._relevance_scorer)
        self._progressive_skill_view = ProgressiveSkillView(self._relevance_scorer)
        self._runtime = SessionRuntime(
            self.session_id,
            self._process_turn_request,
            self._on_runtime_event,
        )

        # Ephemeral agents keep turn state in memory but never load a user session.
        if not self.ephemeral:
            self._load_conversation_history()

        # If this is a new session (no existing history), reset the current conversation counter
        if not self.conversation_history:
            self._reset_current_conversation_tool_calls()

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return str(uuid.uuid4())[:8]

    def _ensure_sessions_dir(self) -> None:
        """Ensure sessions directory exists."""
        self._session_store.root.mkdir(parents=True, exist_ok=True)

    def _load_conversation_history(self) -> None:
        """Load conversation history from session file."""
        data = self._session_store.load()
        if data is None:
            return
        self._session_state = SessionState.from_snapshot(data, self.session_id)
        self._apply_session_state(self._session_state)
        self.console.print(
            f"[dim]Loaded conversation history: {len(self.conversation_history)} messages, "
            f"{len(self.tool_calls_history)} total tool calls[/dim]"
        )

    def _save_conversation_history(self) -> None:
        """Save the current canonical state, propagating commit failures."""
        candidate = self._session_state.clone()
        candidate = self._capture_session_state(candidate)
        if not self.ephemeral:
            candidate.revision = self._session_store.save(
                candidate.to_snapshot(),
                expected_revision=candidate.revision,
            )
        self._session_state = candidate
        self._apply_session_state(candidate)

    def _capture_session_state(self, state: SessionState) -> SessionState:
        """Copy compatibility attributes into one candidate session state."""
        state.tool_calls_history = deepcopy(self.tool_calls_history)
        state.current_conversation_tool_calls = deepcopy(self.current_conversation_tool_calls)
        state.usage.total_llm_calls = self.total_llm_calls
        state.usage.total_input_tokens = self.total_input_tokens
        state.usage.total_output_tokens = self.total_output_tokens
        state.usage.total_cached_input_tokens = self.total_cached_input_tokens
        state.usage.total_cache_write_input_tokens = self.total_cache_write_input_tokens
        state.usage.usage_reported_llm_calls = self.usage_reported_llm_calls
        state.usage.estimated_input_llm_calls = self.estimated_input_llm_calls
        state.usage.last_context_tokens = self.last_context_tokens
        state.usage.last_context_window = self.last_context_window
        state.usage.last_output_tokens = self.last_output_tokens
        state.usage.last_usage_from_api = self.last_usage_from_api
        state.last_memory_review_turn_count = self._last_memory_review_turn_count
        return state

    def _apply_session_state(self, state: SessionState) -> None:
        """Expose one state through the existing Agent compatibility attributes."""
        self.conversation_history = state.messages
        self.tool_calls_history = state.tool_calls_history
        self.current_conversation_tool_calls = state.current_conversation_tool_calls
        self.total_llm_calls = state.usage.total_llm_calls
        self.total_input_tokens = state.usage.total_input_tokens
        self.total_output_tokens = state.usage.total_output_tokens
        self.total_cached_input_tokens = state.usage.total_cached_input_tokens
        self.total_cache_write_input_tokens = state.usage.total_cache_write_input_tokens
        self.usage_reported_llm_calls = state.usage.usage_reported_llm_calls
        self.estimated_input_llm_calls = state.usage.estimated_input_llm_calls
        self.last_context_tokens = state.usage.last_context_tokens
        self.last_context_window = state.usage.last_context_window
        self.last_output_tokens = state.usage.last_output_tokens
        self.last_usage_from_api = state.usage.last_usage_from_api
        self._last_memory_review_turn_count = state.last_memory_review_turn_count

    def _commit_session_state(self, candidate: SessionState) -> None:
        """Persist a complete candidate before publishing it in memory."""
        if not self.ephemeral:
            candidate.revision = self._session_store.save(
                candidate.to_snapshot(),
                expected_revision=candidate.revision,
            )
        self._session_state = candidate
        self._apply_session_state(candidate)

    async def clear_conversation_history(self) -> None:
        """Cancel owned work and atomically replace the session state."""
        await self.reset_session()

    def _resolve_memory_project_root(self, work_dir: Path | None = None) -> Path:
        """Return the project root used for project-scoped persistent memory."""
        configured_root = self.execution_context.get("memory_project_root")
        if configured_root:
            return Path(configured_root).expanduser().resolve()
        return work_dir.resolve() if work_dir else Path.cwd()

    def _memory_history_scope(self, work_dir: Path | None = None) -> str:
        """Return the default scope for automatic conversation history entries."""
        if self.execution_context.get("memory_project_root"):
            return "project"
        return "project" if work_dir else "user"

    @staticmethod
    def _conversation_turn_count(messages: list[dict[str, Any]]) -> int:
        """Count user turns in a conversation snapshot."""
        return sum(1 for msg in messages if msg.get("role") == "user")

    @staticmethod
    def _trim_memory_log_text(text: str, limit: int) -> str:
        """Trim text for compact, readable memory history logs."""
        stripped = text.strip()
        if len(stripped) <= limit:
            return stripped
        return stripped[:limit].rstrip() + "\n[... truncated ...]"

    def _format_conversation_history_entry(self, user_input: str, result: str) -> str:
        """Format an automatic conversation history entry."""
        user = self._trim_memory_log_text(user_input, MEMORY_LOG_USER_LIMIT)
        agent = self._trim_memory_log_text(result, MEMORY_LOG_AGENT_LIMIT)
        return f"User:\n{user}\n\nAgent:\n{agent}"

    def reset_memory_context_snapshot(self) -> None:
        """Refresh memory prompt context on the next system prompt build."""
        self._frozen_memory_project_root = None
        self._frozen_persona_context = ""
        self._frozen_memory_context = ""

    def _get_memory_prompt_context(self, work_dir: Path | None) -> tuple[str, str]:
        """Return the session-frozen persona and memory prompt context."""
        memory_project_root = self._resolve_memory_project_root(work_dir)
        if self._frozen_memory_project_root != memory_project_root:
            memory_manager = get_memory_manager(memory_project_root)
            self._frozen_memory_project_root = memory_project_root
            self._frozen_persona_context = memory_manager.get_persona_context()
            self._frozen_memory_context = memory_manager.get_memory_context()
        return self._frozen_persona_context, self._frozen_memory_context

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

    def get_timeline(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent durable execution events for this session."""
        return self._timeline_store.read(limit=limit)

    def delete_persisted_session(self) -> None:
        """Delete the durable conversation snapshot and execution timeline."""
        self._session_store.delete()
        self._timeline_store.delete()

    def get_token_usage_summary(self) -> dict[str, Any]:
        """Return current context usage and provider-reported session totals."""
        context_window = self.last_context_window
        if not context_window:
            cfg = load_config()
            model_config = cfg.chat.model_config if cfg.chat else None
            context_window = get_model_context_window(
                self._resolve_model_name(cfg),
                model_config=model_config,
            )
        usage_ratio = self.last_context_tokens / context_window if context_window else 0.0
        return {
            "context_tokens": self.last_context_tokens,
            "context_window": context_window,
            "context_usage_ratio": usage_ratio,
            "last_output_tokens": self.last_output_tokens,
            "last_usage_from_api": self.last_usage_from_api,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cached_input_tokens": self.total_cached_input_tokens,
            "total_cache_write_input_tokens": self.total_cache_write_input_tokens,
            "usage_reported_llm_calls": self.usage_reported_llm_calls,
            "estimated_input_llm_calls": self.estimated_input_llm_calls,
            "total_llm_calls": self.total_llm_calls,
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
        if event_type == "message.chunk" or event_type.startswith("tool.call_"):
            active_turn = self._runtime.active_turn
            if active_turn is not None:
                event_data["turn_id"] = active_turn.id
                self._runtime.publish_turn_event(active_turn.id, event_type, event_data)
        if not self.ephemeral and event_type.startswith(("turn.", "tool.", "provider.", "llm.", "context.", "memory.")):
            try:
                self._timeline_store.append(
                    event_type,
                    data,
                    timestamp=event_data["timestamp"],
                )
            except Exception as exc:
                logger.debug("Timeline persistence failed (non-critical): %s", exc)
        for callback in self._event_callbacks:
            with contextlib.suppress(Exception):
                callback(event_type, event_data)

    def _resolve_context_config(self, cfg: AMCPConfig | None = None) -> ContextConfig:
        """Load context config with defaults."""
        resolved = cfg or load_config()
        return resolved.context or ContextConfig()

    def _resolve_turn_config(self) -> AMCPConfig:
        """Resolve one provider/config snapshot for the complete turn.

        Empty AgentSpec model/base URL values inherit the currently active
        provider. Explicit values pin only that field for this agent.
        """
        cfg = deepcopy(load_config())
        chat = cfg.chat or ChatConfig()
        if self.agent_spec.model:
            if chat.model != self.agent_spec.model and (
                chat.model_config is None or chat.model_config.model_id != self.agent_spec.model
            ):
                chat.model_config = None
            chat.model = self.agent_spec.model
        if self.agent_spec.base_url:
            chat.base_url = self.agent_spec.base_url
        cfg.chat = chat
        return cfg

    def _resolve_model_name(self, cfg: AMCPConfig | None = None) -> str:
        """Resolve model name used for budget and token decisions."""
        resolved_cfg = cfg or load_config()
        if self.agent_spec.model:
            return self.agent_spec.model
        if resolved_cfg.chat and resolved_cfg.chat.model:
            return resolved_cfg.chat.model
        return "DeepSeek-V3.1-Terminus"

    def _calculate_context_budget(
        self,
        conversation_tokens: int,
        model_name: str | None = None,
        model_config: ModelConfig | None = None,
        context_config: ContextConfig | None = None,
    ) -> ContextBudget:
        """Calculate context budget for current request."""
        context_cfg = context_config or self._resolve_context_config()
        model = model_name or self._resolve_model_name()
        manager = ContextBudgetManager(model=model, config=context_cfg, model_config=model_config)
        return manager.calculate_budget(conversation_tokens)

    def _trim_to_token_budget(self, text: str, token_budget: int) -> str:
        """Trim long text to token budget using a stable head/tail strategy."""
        if token_budget <= 0 or not text:
            return ""

        current_tokens = estimate_text_tokens(text)
        if current_tokens <= token_budget:
            return text

        # ``estimate_text_tokens`` uses floor(chars / 4), so this is the
        # largest character count that can still fit the requested budget.
        char_budget = token_budget * 4 + 3
        if len(text) <= char_budget:
            return text

        marker = "\n\n[... trimmed for context budget ...]\n\n"
        if len(marker) >= char_budget:
            return text[:char_budget]

        content_budget = char_budget - len(marker)
        head_chars = int(content_budget * 0.7)
        tail_chars = max(content_budget - head_chars, 0)
        if tail_chars > 0:
            return text[:head_chars].rstrip() + marker + text[-tail_chars:].lstrip()
        return text[:head_chars].rstrip() + marker

    def _get_system_prompt(
        self,
        work_dir: Path | None = None,
        user_input: str = "",
        *,
        conversation_tokens: int,
        cfg: AMCPConfig | None = None,
    ) -> str:
        """Get the system prompt budgeted against the actual model conversation."""
        resolved_work_dir = work_dir.resolve() if work_dir else Path.cwd()
        work_dir_str = str(resolved_work_dir)
        cfg = cfg or self._resolve_turn_config()
        context_cfg = cfg.context or ContextConfig()
        model_name = self._resolve_model_name(cfg)

        budget = self._calculate_context_budget(
            conversation_tokens,
            model_name=model_name,
            model_config=cfg.chat.model_config if cfg.chat else None,
            context_config=context_cfg,
        )

        # Note: MCP tools info will be loaded asynchronously during execution
        mcp_tools_info: list[dict[str, Any]] = []

        prompt_vars = {
            "work_dir": work_dir_str,
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
            combined_skills = "\n\n".join(
                part
                for part in (
                    skill_manager.build_skills_summary(),
                    skill_manager.get_active_skills_content(),
                )
                if part
            )
            skills_summary = self._trim_to_token_budget(combined_skills, budget.skills)

        # Get session-frozen persona and memory context. Freezing keeps the
        # prompt prefix stable across a long Telegram session.
        persona_context, memory_context = self._get_memory_prompt_context(work_dir)

        # Respect per-component budgets for every system-prompt section.
        base_prompt = self._trim_to_token_budget(
            base_prompt + "\n\n" + MEMORY_GUIDANCE,
            budget.base_prompt,
        )
        if project_rules:
            project_rules = self._trim_to_token_budget(project_rules, budget.rules)
        if persona_context:
            persona_context = self._trim_to_token_budget(persona_context, budget.memory)
        remaining_memory_budget = max(budget.memory - estimate_text_tokens(persona_context), 0)
        if memory_context:
            memory_context = self._trim_to_token_budget(memory_context, remaining_memory_budget)
        if skills_content:
            skills_content = self._trim_to_token_budget(skills_content, budget.skills)

        # Combine all parts
        combined_prompt = base_prompt
        if persona_context:
            combined_prompt = persona_context + "\n\n" + combined_prompt
        if project_rules:
            combined_prompt += "\n\n" + project_rules
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
                            "name": mcp_tool_name(server_name, tool["name"]),
                            "description": tool.get("description", ""),
                            "server": server_name,
                        }
                    )
            except (OSError, ValueError, KeyError) as e:
                self.console.print(f"[yellow]Warning: Could not load tools from {server_name}: {e}[/yellow]")

        return tools_info

    def _should_limit_tool_calls(self, tool_name: str, cfg: AMCPConfig | None = None) -> bool:
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

        # bash can dump large files and quickly balloon tool context during
        # repo analysis. Keep a configurable per-request loop bound; session
        # totals are still tracked in tool_calls_history for diagnostics.
        if tool_name == "bash":
            limit = self._resolve_bash_tool_limit(cfg)
            if limit > 0 and current_conversation_calls >= limit:
                self.console.print(f"[yellow]Per-request bash limit reached ({limit} calls)[/yellow]")
                return True
            return False

        # MCP tools: 100 per tool per conversation
        return is_mcp_tool_name(tool_name) and current_conversation_calls >= 100

    def _resolve_bash_tool_limit(self, cfg: AMCPConfig | None = None) -> int:
        """Resolve the per-request bash limit; values <= 0 disable this limit."""
        resolved = cfg or load_config()
        configured = resolved.chat.bash_tool_limit if resolved.chat else None
        if isinstance(configured, int) and not isinstance(configured, bool):
            return configured
        return DEFAULT_BASH_TOOL_LIMIT

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
        handle = await self.submit(
            user_input,
            work_dir=work_dir,
            stream=stream,
            show_progress=show_progress,
            priority=priority,
            reject_if_busy=not queue_if_busy,
        )
        try:
            return await handle.wait()
        except TurnCancelledError:
            raise
        except asyncio.CancelledError as cancelled:
            cancel_task = asyncio.create_task(handle.cancel())
            while not cancel_task.done():
                try:
                    await asyncio.shield(cancel_task)
                except asyncio.CancelledError:
                    continue
            if not cancel_task.cancelled():
                with contextlib.suppress(Exception):
                    cancel_task.result()
            raise cancelled

    async def submit(
        self,
        user_input: str,
        *,
        work_dir: Path | None = None,
        stream: bool = True,
        show_progress: bool = True,
        priority: MessagePriority = MessagePriority.NORMAL,
        reject_if_busy: bool = False,
    ) -> TurnHandle:
        """Submit a turn and return a handle that owns its eventual result."""
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeClosedError(f"Agent session {self.session_id} is closed")
            if reject_if_busy and self._runtime.is_busy:
                raise BusyError(f"Session {self.session_id} is busy processing another request")
            return await self._runtime.submit(
                user_input,
                work_dir=work_dir,
                stream=stream,
                show_progress=show_progress,
                priority=priority,
            )

    async def _process_turn_request(self, request: TurnRequest) -> str:
        self.execution_context["turn_id"] = request.id
        return await self._process_message(
            request.prompt,
            request.work_dir,
            request.stream,
            request.show_progress,
        )

    def _on_runtime_event(self, event: str, handle: TurnHandle) -> None:
        data: dict[str, Any] = {
            "turn_id": handle.id,
            "turn_status": handle.status.value,
        }
        outcome = handle.outcome
        if outcome and isinstance(outcome.error, ProviderError):
            data["error_kind"] = outcome.error.kind.value
            data["status_code"] = outcome.error.status_code
        self._emit_event(event, data)

    async def _process_message(self, user_input: str, work_dir: Path | None, stream: bool, show_progress: bool) -> str:
        """
        Process a single message (internal implementation).

        This is the core message processing logic, extracted from run()
        to support queue-based processing.
        """
        committed_state = self._session_state
        draft = committed_state.clone()
        self._apply_session_state(draft)
        self._reset_current_conversation_tool_calls()

        # Run UserPromptSubmit hooks
        try:
            prompt_hook_output = await run_user_prompt_hooks(
                session_id=self.session_id,
                prompt=user_input,
                project_dir=work_dir,
            )
        except BaseException:
            self._apply_session_state(committed_state)
            raise

        # Check if hook denied the prompt
        if not prompt_hook_output.continue_execution:
            if prompt_hook_output.stop_reason:
                self.console.print(f"[yellow]Prompt blocked: {prompt_hook_output.stop_reason}[/yellow]")
            self._apply_session_state(committed_state)
            return prompt_hook_output.stop_reason or "Prompt blocked by hook"

        # Show hook feedback if any
        if prompt_hook_output.feedback:
            self.console.print(f"[dim]Hook: {prompt_hook_output.feedback}[/dim]")

        turn_messages = [{"role": "user", "content": user_input}]

        try:
            with self._create_progress_context(show_progress) as status:
                status.update(f"[bold]Agent {self.name}[/bold] thinking...")

                # Prepare messages with conversation history
                # Freeze provider and related settings for this turn. A
                # `/model use` or config-file edit affects the next turn, but
                # cannot mix providers between chat, compaction, and memory.
                turn_config = self._resolve_turn_config()
                history_to_add = draft.model_context(turn_messages)
                conversation_tokens = estimate_tokens(history_to_add)
                system_prompt = self._get_system_prompt(
                    work_dir,
                    user_input=user_input,
                    conversation_tokens=conversation_tokens,
                    cfg=turn_config,
                )
                messages = [{"role": "system", "content": system_prompt}]

                # Build tools before compaction so their schemas are included in
                # the request-size decision.
                tools, tool_registry = await self._build_tools_and_registry(
                    user_input=user_input,
                    conversation_history=history_to_add,
                    cfg=turn_config,
                )

                # Apply compaction if context is too large
                cfg = turn_config
                model = self._resolve_model_name(cfg)
                compaction_chat = replace(cfg.chat) if cfg.chat else ChatConfig()
                compaction_chat.model = model

                from .llm import create_llm_client

                client = create_llm_client(compaction_chat)
                self._attach_context_overflow_observer(client)
                compactor = SmartCompactor(
                    client,
                    model,
                    model_config=cfg.chat.model_config if cfg.chat else None,
                )

                request_tokens = estimate_request_tokens(messages + history_to_add, tools)
                if (
                    request_tokens > compactor.threshold_tokens
                    and estimate_tokens(history_to_add) >= compactor.config.min_tokens_to_compact
                ):
                    preserve_turns = max(compactor.config.preserve_last // 2, 1)
                    covered_turn_count = max(len(draft.turns) - preserve_turns, 0)
                    previous_covered_turns = draft.checkpoint.covered_turn_count if draft.checkpoint is not None else 0
                    if covered_turn_count > previous_covered_turns:
                        if not self.ephemeral:
                            status.update(f"[bold]Agent {self.name}[/bold] saving memories before compaction...")
                            await self._run_memory_review(
                                conversation_snapshot=history_to_add,
                                system_prompt=system_prompt,
                                work_dir=work_dir,
                                status=status,
                                cfg=turn_config,
                            )
                            self._last_memory_review_turn_count = len(draft.turns) + 1
                        status.update(f"[bold]Agent {self.name}[/bold] compacting context...")
                        covered_message_count = draft.turns[covered_turn_count - 1].end_message
                        previous_message_count = (
                            draft.checkpoint.covered_message_count if draft.checkpoint is not None else 0
                        )
                        checkpoint_input = deepcopy(draft.checkpoint.context) if draft.checkpoint is not None else []
                        checkpoint_input.extend(deepcopy(draft.messages[previous_message_count:covered_message_count]))
                        checkpoint_context, compaction_result = await asyncio.to_thread(
                            compactor.compact_checkpoint,
                            checkpoint_input,
                        )
                        draft.checkpoint = CompactionCheckpoint(
                            context=checkpoint_context,
                            covered_message_count=covered_message_count,
                            covered_turn_count=covered_turn_count,
                            generation=(draft.checkpoint.generation + 1 if draft.checkpoint is not None else 1),
                            strategy=compaction_result.strategy_used.value,
                            strategy_version=1,
                            original_tokens=compaction_result.original_tokens,
                            compacted_tokens=compaction_result.compacted_tokens,
                        )
                        self._emit_event(
                            "context.compacted",
                            {
                                "input_tokens": compaction_result.original_tokens,
                                "output_tokens": compaction_result.compacted_tokens,
                            },
                        )
                        history_to_add = draft.model_context(turn_messages)
                        conversation_tokens = estimate_tokens(history_to_add)
                        system_prompt = self._get_system_prompt(
                            work_dir,
                            user_input=user_input,
                            conversation_tokens=conversation_tokens,
                            cfg=turn_config,
                        )
                        messages[0]["content"] = system_prompt
                        self.reset_memory_context_snapshot()
                        self.console.print("[dim]Context compacted to reduce token usage[/dim]")

                messages.extend(history_to_add)

                # Run chat with tools
                result, tool_messages = await self._run_with_tools(
                    messages=messages,
                    tools=tools,
                    tool_registry=tool_registry,
                    stream=stream,
                    status=status,
                    work_dir=work_dir,
                    cfg=turn_config,
                )

                turn_messages.extend(tool_messages)
                turn_messages.append({"role": "assistant", "content": result})
                self._capture_session_state(draft)
                draft.commit_turn(
                    str(self.execution_context.get("turn_id", uuid.uuid4())),
                    turn_messages,
                )
                turn_count = self._conversation_turn_count(draft.messages)
                periodic_review_due = (
                    not self.ephemeral
                    and turn_count - self._last_memory_review_turn_count >= MEMORY_REVIEW_TURN_INTERVAL
                )
                if periodic_review_due:
                    draft.last_memory_review_turn_count = turn_count
                self._commit_session_state(draft)
                if periodic_review_due:
                    self._schedule_periodic_memory_review(
                        conversation_snapshot=draft.messages,
                        system_prompt=system_prompt,
                        work_dir=work_dir,
                        cfg=turn_config,
                    )

                if not self.ephemeral:
                    # Best-effort projections for normal persistent conversations.
                    try:
                        memory_mgr = get_memory_manager(self._resolve_memory_project_root(work_dir))
                        summary = self._format_conversation_history_entry(user_input, result)
                        memory_mgr.append_history(
                            content=summary,
                            session_id=self.session_id,
                            tags=["conversation"],
                            scope=self._memory_history_scope(work_dir),
                        )
                    except Exception as e:
                        logger.debug(f"Memory history logging failed (non-critical): {e}")

                    try:
                        get_transcript_store().append_turn(
                            session_id=self.session_id,
                            user=user_input,
                            assistant=result,
                            source=str(self.execution_context.get("source", "agent")),
                            chat_id=self.execution_context.get("telegram_chat_id"),
                        )
                    except Exception as e:
                        logger.debug(f"Transcript indexing failed (non-critical): {e}")

                return result

        except asyncio.CancelledError:
            self._apply_session_state(committed_state)
            raise
        except (AgentExecutionError, MaxStepsReached, ProviderError, ToolCallProtocolError):
            self._apply_session_state(committed_state)
            raise
        except Exception as e:
            self._apply_session_state(committed_state)
            self.console.print(Text.assemble(("Agent execution failed: ", "red"), str(e)))
            raise AgentExecutionError(f"Agent execution failed: {e}") from e

    async def _run_memory_review(
        self,
        conversation_snapshot: list[dict[str, Any]],
        system_prompt: str,
        work_dir: Path | None,
        status: Any = None,
        *,
        cfg: AMCPConfig | None = None,
    ) -> bool:
        """Run a pre-compaction memory flush to save durable memories.

        Inspired by openclaw's pre-compaction memory flush: before the
        conversation context is summarized/compacted, give the agent one
        chance to save important user preferences, facts, and identity
        details to persistent memory.  Failures are silently ignored.
        """
        try:
            cfg = cfg or self._resolve_turn_config()
            model = self._resolve_model_name(cfg)
            memory_chat = replace(cfg.chat) if cfg.chat else ChatConfig()
            memory_chat.model = model

            from .llm import create_llm_client

            client = create_llm_client(memory_chat)
            self._attach_context_overflow_observer(client)

            # Build memory-only tool list from the global registry
            from .tools import get_tool_registry

            registry = get_tool_registry()
            memory_tool = registry.get_tool("memory")
            if not memory_tool:
                return False
            memory_tools = [memory_tool.get_spec()]

            self._emit_event("memory.review_start", {})
            memory_project_root = self._resolve_memory_project_root(work_dir)
            memory_executor = ToolExecutor(
                context=ToolExecutionContext(
                    session_id=self.session_id,
                    workspace_root=memory_project_root,
                    turn_id="memory-review",
                ),
                capability=ToolCapability.from_spec(["memory"], [], False),
                exposed_tools={"memory"},
                registry=registry,
                mcp_registry={},
                config=cfg,
            )

            result = await run_memory_review(
                client=client,
                model=model,
                system_prompt=system_prompt,
                conversation_snapshot=conversation_snapshot,
                tools=memory_tools,
                tool_executor=memory_executor,
            )

            saved = bool(result and result.strip() != "Nothing to save.")
            self._emit_event(
                "memory.review_complete",
                {"saved": saved},
            )

            if saved:
                self.console.print("[dim]Memory flush: saved durable memories[/dim]")
            else:
                logger.debug("Memory flush: nothing to save")
            return saved

        except Exception as e:
            logger.debug(f"Memory flush failed (non-critical): {e}")
            return False

    async def flush_memory(
        self,
        work_dir: Path | None = None,
        *,
        conversation_snapshot: list[dict[str, Any]] | None = None,
        status: Any = None,
    ) -> bool:
        """Review the current conversation and persist durable memories."""
        snapshot = list(conversation_snapshot or self.conversation_history)
        if not snapshot:
            return False
        cfg = self._resolve_turn_config()
        system_prompt = self._get_system_prompt(
            work_dir,
            conversation_tokens=estimate_tokens(snapshot),
            cfg=cfg,
        )
        saved = await self._run_memory_review(
            conversation_snapshot=snapshot,
            system_prompt=system_prompt,
            work_dir=work_dir,
            status=status,
            cfg=cfg,
        )
        self._last_memory_review_turn_count = self._conversation_turn_count(snapshot)
        self._save_conversation_history()
        return saved

    async def _maybe_run_periodic_memory_review(
        self,
        conversation_snapshot: list[dict[str, Any]],
        system_prompt: str,
        work_dir: Path | None,
        status: Any = None,
        *,
        persist: bool = True,
    ) -> None:
        """Schedule an isolated memory review every N user turns."""
        if self.ephemeral:
            return
        turn_count = self._conversation_turn_count(conversation_snapshot)
        if turn_count - self._last_memory_review_turn_count < MEMORY_REVIEW_TURN_INTERVAL:
            return
        self._last_memory_review_turn_count = turn_count
        if persist:
            self._save_conversation_history()
        self._schedule_periodic_memory_review(
            conversation_snapshot=conversation_snapshot,
            system_prompt=system_prompt,
            work_dir=work_dir,
        )

    def _schedule_periodic_memory_review(
        self,
        conversation_snapshot: list[dict[str, Any]],
        system_prompt: str,
        work_dir: Path | None,
        cfg: AMCPConfig | None = None,
    ) -> None:
        """Schedule a best-effort review after its checkpoint is committed."""
        if self.ephemeral:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            logger.debug(f"Could not schedule periodic memory review: {exc}")
            return
        task = loop.create_task(
            self._run_isolated_memory_review(
                conversation_snapshot=list(conversation_snapshot),
                system_prompt=system_prompt,
                work_dir=work_dir,
                cfg=deepcopy(cfg) if cfg is not None else None,
            )
        )
        self._pending_memory_review_tasks.add(task)
        task.add_done_callback(self._on_memory_review_task_done)

    async def _run_isolated_memory_review(
        self,
        conversation_snapshot: list[dict[str, Any]],
        system_prompt: str,
        work_dir: Path | None,
        cfg: AMCPConfig | None,
    ) -> None:
        """Run a background memory review without mutating chat history."""
        await self._run_memory_review(
            conversation_snapshot=conversation_snapshot,
            system_prompt=system_prompt,
            work_dir=work_dir,
            status=None,
            cfg=cfg,
        )

    def _on_memory_review_task_done(self, task: asyncio.Task[None]) -> None:
        """Remove completed background review tasks and log failures."""
        self._pending_memory_review_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as e:
            logger.debug(f"Periodic memory review failed (non-critical): {e}")

    def is_busy(self) -> bool:
        """Check if this agent's session is currently busy."""
        return self._runtime.is_busy

    def queued_count(self) -> int:
        """Get the number of queued messages for this session."""
        return self._runtime.queued_count

    def queued_prompts(self) -> list[str]:
        """Get list of queued prompts for this session."""
        return self._runtime.queued_prompts()

    async def clear_queue(self) -> int:
        """Clear all queued messages for this session."""
        return await self._runtime.clear_queue()

    async def cancel(self, *, clear_queue: bool = False) -> CancellationResult:
        """Cancel current work and return the runtime's actual cancellation result."""
        async with self._lifecycle_lock:
            if clear_queue:
                result = await self._runtime.cancel_all()
            else:
                active_cancelled = await self._runtime.cancel_active()
                result = CancellationResult(
                    active_cancelled=active_cancelled,
                    queued_cancelled=0,
                )
            await self._cancel_memory_review_tasks()
            await self._cancel_delegated_tasks()
            return result

    async def cancel_turn(self, turn_id: str) -> bool:
        """Cancel one active or queued turn without creating another owner."""
        async with self._lifecycle_lock:
            handle = self._runtime.get_turn(turn_id)
            was_active = handle is not None and self._runtime.active_turn is handle
            cancelled = await self._runtime.cancel_turn(turn_id)
            if cancelled and was_active:
                await self._cancel_delegated_tasks()
            return cancelled

    async def reset_session(self) -> None:
        """Cancel all work and atomically replace the committed session state."""
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeClosedError(f"Agent session {self.session_id} is closed")
            await self._runtime.cancel_all()
            await self._cancel_memory_review_tasks()
            await self._cancel_delegated_tasks()
            candidate = SessionState(
                session_id=self.session_id,
                agent_name=self.name,
                revision=self._session_state.revision,
            )
            if not self.ephemeral:
                candidate.revision = self._session_store.save(
                    candidate.to_snapshot(),
                    expected_revision=candidate.revision,
                )
            self._session_state = candidate
            self._apply_session_state(candidate)
            self.current_request_llm_calls = 0
            self.current_request_tool_calls = 0
            self.reset_memory_context_snapshot()

    async def _cancel_delegated_tasks(self) -> int:
        """Cancel and await delegated tasks owned by this Agent session."""
        return await self._task_manager.cancel_for_session(self.session_id)

    async def _cancel_memory_review_tasks(self) -> None:
        """Cancel and await pending background memory reviews."""
        tasks = list(self._pending_memory_review_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        """Permanently stop the Agent and await all session-owned resources."""
        async with self._lifecycle_lock:
            if self._close_complete:
                return
            self._closed = True
            await self._runtime.close()
            await self._cancel_delegated_tasks()
            await self._cancel_memory_review_tasks()
            self._close_complete = True

    def get_queue_status(self) -> dict[str, Any]:
        """Get queue status for this session."""
        active = self._runtime.active_turn
        return {
            "session_id": self.session_id,
            "status": self._runtime.status.value,
            "is_busy": self._runtime.is_busy,
            "active_turn_id": active.id if active else None,
            "queued_count": self._runtime.queued_count,
            "queued_prompts": self._runtime.queued_prompts(),
        }

    def get_turn(self, turn_id: str) -> TurnHandle | None:
        """Return a turn handle owned by this session."""
        return self._runtime.get_turn(turn_id)

    async def _build_tools_and_registry(
        self,
        user_input: str = "",
        conversation_history: list[dict[str, Any]] | None = None,
        *,
        cfg: AMCPConfig | None = None,
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

        capability = ToolCapability.from_spec(
            self.agent_spec.tools,
            self.agent_spec.exclude_tools,
            self.agent_spec.can_delegate,
        )

        tool_registry = get_tool_registry()
        for tool_name in tool_registry.list_tools():
            if not capability.allows(tool_name):
                continue
            tool_spec = tool_registry.get_tool_spec(tool_name)
            if tool_spec:
                tools.append(tool_spec)

        # Load MCP tools
        cfg = cfg or self._resolve_turn_config()
        chat_cfg = cfg.chat

        # Decide which servers to include
        if chat_cfg and chat_cfg.mcp_tools_enabled is False:
            selected = []
        elif chat_cfg and chat_cfg.mcp_servers:
            selected = [s for s in chat_cfg.mcp_servers if s in cfg.servers]
        else:
            selected = list(cfg.servers.keys())

        # Load MCP tools asynchronously (single call per server). Server and
        # tool names are untrusted, and providers disagree on legal function
        # names (Kimi rejects the dots Gemini accepts), so every MCP tool is
        # exposed under a sanitized alias that the registry maps back to its
        # (server, tool) pair.
        exposed_names = {tool_name for tool in tools if (tool_name := tool.get("function", {}).get("name"))}
        for name in selected:
            try:
                server = cfg.servers[name]
                info_list = await list_mcp_tools(server)
                for info in info_list:
                    tname = info.get("name") or "tool"
                    oname = unique_function_name(mcp_tool_name(name, tname), exposed_names)
                    if not capability.allows(oname):
                        continue
                    exposed_names.add(oname)
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
        budget = self._calculate_context_budget(
            conversation_tokens,
            model_name=self._resolve_model_name(cfg),
            model_config=cfg.chat.model_config if cfg.chat else None,
            context_config=context_cfg,
        )
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
        work_dir: Path | None = None,
        *,
        cfg: AMCPConfig | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Run chat with tools and enhanced tracking."""
        cfg = cfg or self._resolve_turn_config()

        # Use new LLM client abstraction
        from .llm import create_llm_client

        llm_client = create_llm_client(cfg.chat)
        self._attach_context_overflow_observer(llm_client)

        # Override the chat function to add our tracking
        result = await self._enhanced_chat_with_tools(
            llm_client=llm_client,
            messages=messages,
            tools=tools,
            tool_registry=tool_registry,
            stream=stream,
            status=status,
            work_dir=work_dir,
            return_message_delta=True,
            cfg=cfg,
        )
        assert isinstance(result, tuple)
        return result

    async def _enhanced_chat_with_tools(
        self,
        llm_client,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_registry: dict[str, Any],
        stream: bool,
        status: Status,
        work_dir: Path | None = None,
        max_steps: int | None = None,
        *,
        return_message_delta: bool = False,
        cfg: AMCPConfig | None = None,
    ) -> str | tuple[str, list[dict[str, Any]]]:
        """Enhanced version of _chat_with_tools with better tracking."""
        max_steps = max_steps or self.max_steps

        # Reset per-request counters at the start of each request
        self.current_request_tool_calls = 0
        self.current_request_llm_calls = 0

        # Create a working copy of messages
        messages = [dict(message) for message in messages]
        message_delta: list[dict[str, Any]] = []

        def append_canonical(message: dict[str, Any]) -> None:
            messages.append(message)
            message_delta.append(deepcopy(message))

        def completed(text: str) -> str | tuple[str, list[dict[str, Any]]]:
            if return_message_delta:
                return text, message_delta
            return text

        used_tools = False

        cfg = cfg or self._resolve_turn_config()
        model_config = cfg.chat.model_config if cfg.chat else None
        model = getattr(llm_client, "model", None) or self._resolve_model_name(cfg)
        workspace_root = (work_dir or Path.cwd()).resolve()
        exposed_tools = {name for tool in tools if (name := tool.get("function", {}).get("name"))}
        capability = ToolCapability.from_spec(
            self.agent_spec.tools,
            self.agent_spec.exclude_tools,
            self.agent_spec.can_delegate,
        )
        from .tools import get_tool_registry

        executor = ToolExecutor(
            context=ToolExecutionContext(
                session_id=self.session_id,
                workspace_root=workspace_root,
                turn_id=str(self.execution_context.get("turn_id", "direct")),
            ),
            capability=capability,
            exposed_tools=exposed_tools,
            registry=get_tool_registry(),
            mcp_registry=tool_registry,
            config=cfg,
            task_manager=self._task_manager,
        )
        compaction_config = CompactionConfig()
        context_window = get_model_context_window(model, model_config=model_config)
        input_token_budget = int(
            context_window * (1 - compaction_config.safety_margin) * compaction_config.threshold_ratio
        )

        for step in range(max_steps):
            self.step_count = step + 1
            status.update(f"[bold]Agent {self.name}[/bold] - LLM Call {self.current_request_llm_calls + 1}")

            # Define stream callback if streaming is enabled
            stream_callback = None
            if stream:

                def _stream_callback(chunk: str):
                    self._emit_event("message.chunk", {"content": chunk})

                stream_callback = _stream_callback

            messages = self._fit_tool_context(messages, tools, input_token_budget)
            estimated_input_tokens = estimate_request_tokens(messages, tools)
            try:
                resp = await self._call_llm(
                    llm_client,
                    messages=messages,
                    tools=tools,
                    stream_callback=stream_callback,
                    cfg=cfg.chat,
                )
            except Exception as call_error:
                if isinstance(call_error, ProviderError) and call_error.partial_output:
                    raise
                if not _is_tool_call_pairing_error(call_error):
                    raise
                logger.warning(
                    "Provider rejected tool-call history (%s); repairing pairing and retrying once",
                    call_error,
                )
                messages = self._fit_tool_context(
                    _repair_tool_call_pairing(messages),
                    tools,
                    input_token_budget,
                )
                estimated_input_tokens = estimate_request_tokens(messages, tools)
                resp = await self._call_llm(
                    llm_client,
                    messages=messages,
                    tools=tools,
                    stream_callback=stream_callback,
                    cfg=cfg.chat,
                )
            self._record_llm_usage(resp, estimated_input_tokens, context_window)

            if resp.tool_calls:
                try:
                    tool_calls = normalize_tool_calls(resp.tool_calls)
                except ToolCallProtocolError as protocol_error:
                    if protocol_error.tool_calls is None:
                        raise
                    logger.warning(
                        "Provider returned malformed tool calls (%s); synthesizing tool results",
                        protocol_error,
                    )
                    tool_calls = normalize_tool_calls(protocol_error.tool_calls)
                used_tools = True
                status.update(f"[bold]Agent {self.name}[/bold] - Executing {len(tool_calls)} tool(s)...")

                # Check if any tool should be limited before processing
                limited_tools = []
                for tc in tool_calls:
                    tool_name = tc.name
                    if self._should_limit_tool_calls(tool_name, cfg):
                        limited_tools.append(tool_name)

                if limited_tools:
                    status.update(
                        f"[bold]Agent {self.name}[/bold] - Tools {limited_tools} limited, forcing response..."
                    )
                    self.console.print(f"[yellow]Tools {limited_tools} limited, forcing response[/yellow]")
                    append_canonical(
                        {
                            "role": "assistant",
                            "content": resp.content or "",
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.name,
                                        "arguments": tc.raw_arguments,
                                    },
                                }
                                | ({"extra_content": tc.extra_content} if tc.extra_content else {})
                                for tc in tool_calls
                            ],
                        }
                    )
                    for tc in tool_calls:
                        append_canonical(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "name": tc.name,
                                "content": (
                                    "Tool call limited: further calls to this tool are not allowed in this request"
                                ),
                            }
                        )
                    # Add system message to force response
                    messages.append(
                        {
                            "role": "system",
                            "content": f"You have already called the following tools too many times: {', '.join(limited_tools)}. Please analyze the information you have and provide your response without calling these tools again.",
                        }
                    )
                    # Get a final response from the LLM with the current messages
                    try:
                        messages = self._fit_tool_context(messages, [], input_token_budget)
                        estimated_input_tokens = estimate_request_tokens(messages)
                        final_resp = await self._call_llm(
                            llm_client,
                            messages=messages,
                            cfg=cfg.chat,
                        )
                        self._record_llm_usage(final_resp, estimated_input_tokens, context_window)
                        final_text = final_resp.content or ""
                        status.update(f"[bold]Agent {self.name}[/bold] - ✅ Complete")
                        return completed(final_text)
                    except Exception as e:
                        status.update(f"[bold]Agent {self.name}[/bold] - ⚠️ Error getting final response")
                        if isinstance(e, ProviderError):
                            raise
                        raise AgentExecutionError(f"Could not get final response: {e}") from e

                append_canonical(
                    {
                        "role": "assistant",
                        "content": resp.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.raw_arguments,
                                },
                            }
                            | ({"extra_content": tc.extra_content} if tc.extra_content else {})
                            for tc in tool_calls
                        ],
                    }
                )

                # Process tool calls with Live UI
                with LiveUI() as live_ui:
                    for tc in tool_calls:
                        tool_name = tc.name
                        tool_id = tc.id
                        if tc.argument_error:
                            tool_result_text = f"Tool argument error: {tc.argument_error}"
                            block = live_ui.add_tool(tool_name, {})
                            live_ui.finish_tool(block, success=False, result=tool_result_text)
                            append_canonical(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_name,
                                    "content": tool_result_text,
                                }
                            )
                            continue
                        assert tc.arguments is not None
                        args = tc.arguments

                        if tool_name not in exposed_tools or not capability.allows(tool_name):
                            tool_result_text = f"Tool permission denied: '{tool_name}' is not authorized"
                            block = live_ui.add_tool(tool_name, args)
                            live_ui.finish_tool(block, success=False, result=tool_result_text)
                            self._emit_event(
                                "tool.call_denied",
                                {
                                    "tool_name": tool_name,
                                    "tool_id": tool_id,
                                    "reason": tool_result_text,
                                },
                            )
                            append_canonical(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_name,
                                    "content": tool_result_text,
                                }
                            )
                            continue

                        # Hooks must inspect the same canonical arguments that
                        # execution will use. For example, grep's common
                        # ``path`` near-miss becomes ``paths`` here.
                        args = executor.prepare_model_arguments(tool_name, args)

                        # Run PreToolUse hooks
                        pre_hook_output = await run_pre_tool_use_hooks(
                            session_id=self.session_id,
                            tool_name=tool_name,
                            tool_input=args,
                            tool_use_id=tool_id,
                            project_dir=workspace_root,
                        )

                        # Check hook decision
                        if pre_hook_output.decision == HookDecision.DENY:
                            # Tool execution denied by hook
                            tool_result_text = (
                                f"Tool denied by hook: {pre_hook_output.decision_reason or 'No reason given'}"
                            )
                            block = live_ui.add_tool(tool_name, args)
                            live_ui.finish_tool(block, success=False, result=tool_result_text)
                            append_canonical(
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
                            "args": tc.raw_arguments,
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
                            tool_result = await executor.execute(tool_name, args)
                            if tool_result.success:
                                tool_result_text = tool_result.content
                                tool_response_data = {
                                    "success": True,
                                    "content": tool_result_text,
                                }
                                live_ui.finish_tool(block, success=True, result=tool_result_text)
                            else:
                                tool_result_text = f"Error: {tool_result.error}"
                                tool_response_data = {
                                    "success": False,
                                    "error": tool_result.error,
                                }
                                live_ui.finish_tool(block, success=False, result=tool_result_text)

                            # Run PostToolUse hooks
                            post_hook_output = await run_post_tool_use_hooks(
                                session_id=self.session_id,
                                tool_name=tool_name,
                                tool_input=args,
                                tool_response=tool_response_data,
                                tool_use_id=tool_id,
                                project_dir=workspace_root,
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

                            append_canonical(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_name,
                                    "content": truncated_result,
                                }
                            )

                        except asyncio.CancelledError:
                            tool_duration_ms = (time.time() - tool_start_time) * 1000
                            self._emit_event(
                                "tool.call_cancelled",
                                {
                                    "tool_name": tool_name,
                                    "tool_id": tool_id,
                                    "success": False,
                                    "settled": True,
                                    "duration_ms": tool_duration_ms,
                                },
                            )
                            raise
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

                            append_canonical(
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
                return completed(final_text)

        # Max steps reached
        status.update(f"[bold]Agent {self.name}[/bold] - ⚠️ Max steps reached")
        raise MaxStepsReached(self.max_steps)

    async def _call_llm(
        self,
        llm_client: Any,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream_callback: Any | None = None,
        cfg: ChatConfig | None = None,
    ) -> Any:
        """Call a provider with timeout and bounded transient-error retries."""
        policy = cfg or ChatConfig()
        timeout = max(0.1, float(policy.request_timeout_seconds))
        max_retries = max(0, int(policy.max_retries))
        base_delay = max(0.0, float(policy.retry_base_delay_seconds))
        emitted_output = False

        def tracked_callback(chunk: str) -> None:
            nonlocal emitted_output
            emitted_output = True
            if stream_callback is not None:
                stream_callback(chunk)

        callback = tracked_callback if stream_callback is not None else None

        async def call_once() -> Any:
            async_chat = getattr(llm_client, "achat", None)
            if callable(async_chat):
                return await async_chat(
                    messages=messages,
                    tools=tools,
                    stream_callback=callback,
                )
            return await asyncio.to_thread(
                llm_client.chat,
                messages=messages,
                tools=tools,
                stream_callback=callback,
            )

        for attempt in range(max_retries + 1):
            try:
                self.current_request_llm_calls += 1
                self.total_llm_calls += 1
                return await asyncio.wait_for(call_once(), timeout=timeout)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                provider_error = classify_provider_error(exc, partial_output=emitted_output)
                if isinstance(provider_error, ContextOverflowError):
                    if not provider_error.timeline_emitted:
                        self._record_context_overflow(provider_error)
                    if provider_error is exc:
                        raise
                    raise provider_error from exc
                if not provider_error.retryable or attempt >= max_retries:
                    self._emit_event(
                        "provider.error",
                        {
                            "error_kind": provider_error.kind.value,
                            "status_code": provider_error.status_code,
                            "partial_output": provider_error.partial_output,
                            "attempt": attempt + 1,
                        },
                    )
                    if provider_error is exc:
                        raise
                    raise provider_error from exc

                retry_delay = provider_error.retry_after
                if retry_delay is None:
                    retry_delay = random.uniform(0.0, min(30.0, base_delay * (2**attempt)))
                retry_delay = min(retry_delay, 60.0)
                self._emit_event(
                    "provider.retry",
                    {
                        "error_kind": provider_error.kind.value,
                        "status_code": provider_error.status_code,
                        "attempt": attempt + 2,
                        "delay_seconds": retry_delay,
                    },
                )
                await asyncio.sleep(retry_delay)

        raise AssertionError("provider retry loop exhausted without returning or raising")

    def _attach_context_overflow_observer(self, llm_client: Any) -> None:
        """Attach timeline reporting to a client when it supports local overflow checks."""
        setter = getattr(llm_client, "set_context_overflow_callback", None)
        if callable(setter):
            setter(self._record_context_overflow)

    def _record_context_overflow(self, error: ContextOverflowError) -> None:
        """Record one sanitized context-overflow event for the active session."""
        if error.timeline_emitted:
            return
        error.timeline_emitted = True
        self._emit_event(
            "context.overflow",
            {
                "input_tokens": error.input_tokens,
                "input_limit": error.input_limit,
                "context_window": error.context_window,
                "output_reserve": error.output_reserve,
            },
        )

    def _record_llm_usage(
        self,
        response: Any,
        estimated_input_tokens: int,
        context_window: int,
    ) -> None:
        """Record context occupancy and provider-reported token consumption."""
        usage = getattr(response, "usage", None)
        self.last_context_window = context_window
        if usage is None:
            self.last_context_tokens = estimated_input_tokens
            self.last_output_tokens = None
            self.last_usage_from_api = False
            self.total_input_tokens += estimated_input_tokens
            self.estimated_input_llm_calls += 1
            self._emit_event(
                "llm.usage",
                {
                    "input_tokens": estimated_input_tokens,
                    "output_tokens": None,
                    "context_window": context_window,
                    "usage_from_api": False,
                },
            )
            return

        self.last_context_tokens = usage.prompt_tokens
        self.last_output_tokens = usage.output_tokens
        self.last_usage_from_api = True
        self.total_input_tokens += usage.prompt_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_cached_input_tokens += usage.cached_input_tokens
        self.total_cache_write_input_tokens += usage.cache_write_input_tokens
        self.usage_reported_llm_calls += 1
        self._emit_event(
            "llm.usage",
            {
                "input_tokens": usage.prompt_tokens,
                "output_tokens": usage.output_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "total_tokens": usage.total_tokens,
                "context_window": context_window,
                "usage_from_api": True,
            },
        )

    @staticmethod
    def _fit_tool_context(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        token_budget: int,
    ) -> list[dict[str, Any]]:
        """Fit request-local tool exchanges into the model input budget."""
        fitted = [dict(message) for message in messages]
        if estimate_request_tokens(fitted, tools) <= token_budget:
            return _repair_tool_call_pairing(fitted)

        tool_indexes = [i for i, message in enumerate(fitted) if message.get("role") == "tool"]

        # Retain useful head/tail excerpts, shrinking oldest results first.
        for index in tool_indexes:
            content = fitted[index].get("content")
            if not isinstance(content, str) or len(content) <= 1200:
                continue
            fitted[index]["content"] = (
                content[:600] + "\n... [tool result trimmed for context budget] ...\n" + content[-600:]
            )
            if estimate_request_tokens(fitted, tools) <= token_budget:
                return fitted

        # Remove oldest complete tool-call batches, preferring the latest batch.
        batch_ranges: list[tuple[int, int]] = []
        index = 0
        while index < len(fitted):
            message = fitted[index]
            if message.get("role") != "assistant" or not message.get("tool_calls"):
                index += 1
                continue
            call_ids = {call.get("id") for call in message["tool_calls"]}
            end = index + 1
            seen_ids: set[str | None] = set()
            while end < len(fitted) and fitted[end].get("role") == "tool":
                seen_ids.add(fitted[end].get("tool_call_id"))
                end += 1
            if call_ids and call_ids <= seen_ids:
                batch_ranges.append((index, end))
            index = end

        for start, end in reversed(batch_ranges[:-1]):
            del fitted[start:end]
            if estimate_request_tokens(fitted, tools) <= token_budget:
                return fitted

        # If the newest result alone is too large, reduce all remaining results
        # to explicit placeholders rather than sending a known-oversized request.
        for message in fitted:
            if message.get("role") == "tool" and message.get("content"):
                message["content"] = "[Tool result omitted: context budget exceeded]"
        return _repair_tool_call_pairing(fitted)

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
    *,
    ephemeral: bool = False,
) -> Agent:
    """
    Create an Agent from an AgentConfig.

    This is the primary way to instantiate agents using the multi-agent system.

    Args:
        config: AgentConfig from the multi_agent module
        session_id: Optional session ID for conversation persistence
        ephemeral: Disable automatic session, timeline, history, and transcript persistence

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

    return Agent(agent_spec=spec, session_id=session_id, ephemeral=ephemeral)


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
