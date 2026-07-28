"""Canonical, versioned state for durable AMCP sessions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


class InvalidSessionStateError(ValueError):
    """Raised when a session snapshot violates the canonical message contract."""


@dataclass
class CanonicalTurn:
    """A committed range of canonical conversation messages."""

    turn_id: str
    start_message: int
    end_message: int
    completed_at: str


@dataclass
class CompactionCheckpoint:
    """Persisted compacted context covering a complete prefix of turns."""

    context: list[dict[str, Any]]
    covered_message_count: int
    covered_turn_count: int
    generation: int
    strategy: str
    strategy_version: int
    original_tokens: int
    compacted_tokens: int


@dataclass
class SessionUsage:
    """Usage and context counters that affect session diagnostics."""

    total_llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_input_tokens: int = 0
    total_cache_write_input_tokens: int = 0
    usage_reported_llm_calls: int = 0
    estimated_input_llm_calls: int = 0
    last_context_tokens: int = 0
    last_context_window: int = 0
    last_output_tokens: int | None = None
    last_usage_from_api: bool = False


@dataclass
class SessionState:
    """The single committed state of an AMCP session."""

    session_id: str
    agent_name: str
    revision: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    messages: list[dict[str, Any]] = field(default_factory=list)
    turns: list[CanonicalTurn] = field(default_factory=list)
    checkpoint: CompactionCheckpoint | None = None
    usage: SessionUsage = field(default_factory=SessionUsage)
    tool_calls_history: list[dict[str, Any]] = field(default_factory=list)
    current_conversation_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    last_memory_review_turn_count: int = 0

    def clone(self) -> SessionState:
        """Return an isolated draft copy."""
        return deepcopy(self)

    def model_context(self, draft_messages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Build canonical model context from a checkpoint and committed suffix."""
        start = 0
        context: list[dict[str, Any]] = []
        if self.checkpoint is not None:
            start = self.checkpoint.covered_message_count
            context.extend(deepcopy(self.checkpoint.context))
        context.extend(deepcopy(self.messages[start:]))
        if draft_messages:
            context.extend(deepcopy(draft_messages))
        return context

    def commit_turn(self, turn_id: str, message_delta: list[dict[str, Any]]) -> None:
        """Append one validated, complete turn to this draft."""
        _validate_complete_turn(message_delta)
        start = len(self.messages)
        self.messages.extend(deepcopy(message_delta))
        self.turns.append(
            CanonicalTurn(
                turn_id=turn_id,
                start_message=start,
                end_message=len(self.messages),
                completed_at=datetime.now().isoformat(),
            )
        )

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize this state to the schema v2 snapshot shape."""
        validate_session_state(self)
        return {
            "agent_name": self.agent_name,
            "revision": self.revision,
            "created_at": self.created_at,
            "conversation": {
                "messages": deepcopy(self.messages),
                "turns": [asdict(turn) for turn in self.turns],
            },
            "compaction_checkpoint": asdict(self.checkpoint) if self.checkpoint else None,
            "usage": asdict(self.usage),
            "diagnostics": {
                "tool_calls_history": deepcopy(self.tool_calls_history),
                "current_conversation_tool_calls": deepcopy(self.current_conversation_tool_calls),
                "last_memory_review_turn_count": self.last_memory_review_turn_count,
            },
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any], session_id: str) -> SessionState:
        """Load a schema v2 snapshot after strict structural validation."""
        conversation = data.get("conversation")
        if not isinstance(conversation, dict):
            raise InvalidSessionStateError("Session conversation must be an object")
        messages = conversation.get("messages")
        turns_data = conversation.get("turns")
        if not isinstance(messages, list) or not isinstance(turns_data, list):
            raise InvalidSessionStateError("Session conversation messages and turns must be lists")
        try:
            turns = [CanonicalTurn(**turn) for turn in turns_data]
            checkpoint_data = data.get("compaction_checkpoint")
            checkpoint = CompactionCheckpoint(**checkpoint_data) if checkpoint_data is not None else None
            usage = SessionUsage(**data.get("usage", {}))
        except (TypeError, ValueError) as exc:
            raise InvalidSessionStateError(f"Invalid session state fields: {exc}") from exc

        diagnostics = data.get("diagnostics", {})
        if not isinstance(diagnostics, dict):
            raise InvalidSessionStateError("Session diagnostics must be an object")
        state = cls(
            session_id=session_id,
            agent_name=str(data.get("agent_name", "default")),
            revision=int(data.get("revision", 0)),
            created_at=str(data.get("created_at", datetime.now().isoformat())),
            messages=deepcopy(messages),
            turns=turns,
            checkpoint=checkpoint,
            usage=usage,
            tool_calls_history=deepcopy(diagnostics.get("tool_calls_history", [])),
            current_conversation_tool_calls=deepcopy(diagnostics.get("current_conversation_tool_calls", [])),
            last_memory_review_turn_count=int(diagnostics.get("last_memory_review_turn_count", 0)),
        )
        validate_session_state(state)
        return state


def validate_session_state(state: SessionState) -> None:
    """Validate turn ranges, tool batches, and checkpoint coverage."""
    if type(state.revision) is not int or state.revision < 0:
        raise InvalidSessionStateError("Session revision must be a non-negative integer")
    if any(not isinstance(message, dict) for message in state.messages):
        raise InvalidSessionStateError("Canonical messages must be objects")
    expected_start = 0
    turn_ids: set[str] = set()
    for turn in state.turns:
        if not isinstance(turn.turn_id, str) or not turn.turn_id or turn.turn_id in turn_ids:
            raise InvalidSessionStateError("Committed turn IDs must be unique")
        if (
            type(turn.start_message) is not int
            or type(turn.end_message) is not int
            or not isinstance(turn.completed_at, str)
        ):
            raise InvalidSessionStateError("Committed turn fields have invalid types")
        turn_ids.add(turn.turn_id)
        if (
            turn.start_message != expected_start
            or turn.end_message <= turn.start_message
            or turn.end_message > len(state.messages)
        ):
            raise InvalidSessionStateError("Session turn ranges must be contiguous and valid")
        turn_messages = state.messages[turn.start_message : turn.end_message]
        _validate_complete_turn(turn_messages)
        expected_start = turn.end_message
    if expected_start != len(state.messages):
        raise InvalidSessionStateError("Every canonical message must belong to one turn")

    checkpoint = state.checkpoint
    if checkpoint is None:
        return
    if (
        not isinstance(checkpoint.context, list)
        or not checkpoint.context
        or any(
            not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}
            for message in checkpoint.context
        )
    ):
        raise InvalidSessionStateError("Compaction checkpoint context must be a non-empty list")
    integer_fields = (
        checkpoint.covered_message_count,
        checkpoint.covered_turn_count,
        checkpoint.generation,
        checkpoint.strategy_version,
        checkpoint.original_tokens,
        checkpoint.compacted_tokens,
    )
    if any(type(value) is not int for value in integer_fields) or not isinstance(checkpoint.strategy, str):
        raise InvalidSessionStateError("Compaction checkpoint fields have invalid types")
    if not 0 < checkpoint.covered_turn_count <= len(state.turns):
        raise InvalidSessionStateError("Compaction checkpoint has invalid turn coverage")
    boundary = state.turns[checkpoint.covered_turn_count - 1].end_message
    if checkpoint.covered_message_count != boundary:
        raise InvalidSessionStateError("Compaction checkpoint coverage must end on a complete turn boundary")
    if checkpoint.generation < 1 or checkpoint.strategy_version < 1:
        raise InvalidSessionStateError("Compaction checkpoint generation is invalid")


def _validate_complete_turn(messages: list[dict[str, Any]]) -> None:
    if (
        len(messages) < 2
        or messages[0].get("role") != "user"
        or messages[-1].get("role") != "assistant"
        or messages[-1].get("tool_calls")
    ):
        raise InvalidSessionStateError("A committed turn must start with user and end with a final assistant message")

    index = 1
    while index < len(messages) - 1:
        assistant = messages[index]
        calls = assistant.get("tool_calls") if assistant.get("role") == "assistant" else None
        if not isinstance(calls, list) or not calls:
            raise InvalidSessionStateError("Intermediate assistant messages must contain tool calls")
        call_ids = [call.get("id") for call in calls if isinstance(call, dict)]
        if len(call_ids) != len(calls) or any(not isinstance(call_id, str) or not call_id for call_id in call_ids):
            raise InvalidSessionStateError("Tool calls must have non-empty IDs")
        if len(set(call_ids)) != len(call_ids):
            raise InvalidSessionStateError("Tool call IDs must be unique within a batch")
        results = messages[index + 1 : index + 1 + len(call_ids)]
        if len(results) != len(call_ids) or [result.get("tool_call_id") for result in results] != call_ids:
            raise InvalidSessionStateError("Every tool call must have one ordered tool result")
        if any(result.get("role") != "tool" for result in results):
            raise InvalidSessionStateError("Tool results must use the tool role")
        index += len(call_ids) + 1
