"""
Smart Context Compaction for AMCP.

This module provides intelligent context compaction that dynamically adjusts
thresholds based on the model's context window size. It supports multiple
compaction strategies and integrates with the event bus for monitoring.

Key Features:
- Dynamic threshold based on model context windows
- Multiple compaction strategies (summary, truncate, sliding window)
- Token estimation with tiktoken support
- Preservation of important context (recent messages, tool results)
- Event emission for monitoring compaction events
- Configurable safety margins

Built-in Fallback Models (when models.dev unavailable):
- OpenAI: GPT-5.1 Codex (400K), GPT-5.2 (400K)
- Anthropic: Claude 4.5 Sonnet (200K), Claude 4.5 Opus (200K)
- Google: Gemini 3 Pro (1M)
- ZAI/GLM: GLM-4.6 (204K), GLM-4.7 (204K)
- MiniMax: MiniMax M2.1 (204K)

Example:
    from amcp.compaction import SmartCompactor, get_model_context_window

    # Get context window for model
    ctx_window = get_model_context_window("gpt-4-turbo")  # 128000

    # Create compactor
    compactor = SmartCompactor(client, model="gpt-4-turbo")

    # Check if compaction needed
    if compactor.should_compact(messages):
        compacted = await compactor.compact_async(messages)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)


# Model context window sizes (in tokens) - Built-in fallback models
# Used when models.dev database is unavailable
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-5.1-codex": 400_000,
    "gpt-5.2": 400_000,
    # Anthropic
    "claude-4.5-sonnet": 200_000,
    "claude-4.5-opus": 200_000,
    # Google
    "gemini-3-pro": 1_048_576,
    # ZAI/GLM
    "glm-4.6": 204_800,
    "glm-4.7": 204_800,
    # MiniMax
    "minimax-m2.1": 204_800,
}

# Default context window for unknown models
DEFAULT_CONTEXT_WINDOW = 32_000


class CompactionStrategy(Enum):
    """Strategies for context compaction."""

    SUMMARY = "summary"  # Use LLM to summarize old messages
    TRUNCATE = "truncate"  # Simple truncation of old messages
    SLIDING_WINDOW = "sliding_window"  # Keep a sliding window of recent messages
    HYBRID = "hybrid"  # Combination of summary and sliding window


@dataclass
class CompactionConfig:
    """Configuration for context compaction.

    Attributes:
        strategy: Compaction strategy to use
        threshold_ratio: Trigger compaction when usage exceeds this ratio of context window
        target_ratio: Aim to reduce context to this ratio after compaction
        preserve_last: Number of recent user/assistant messages to preserve
        preserve_tool_results: Whether to preserve recent tool results
        max_tool_results: Maximum number of tool results to preserve
        min_tokens_to_compact: Minimum tokens before considering compaction
        safety_margin: Extra margin to leave for response generation
    """

    strategy: CompactionStrategy = CompactionStrategy.SUMMARY
    threshold_ratio: float = 0.7  # Compact when > 70% of context used
    target_ratio: float = 0.3  # Aim for 30% after compaction
    preserve_last: int = 6  # Keep last 6 user/assistant messages
    preserve_tool_results: bool = True
    max_tool_results: int = 10
    min_tokens_to_compact: int = 5000  # Don't compact tiny contexts
    safety_margin: float = 0.1  # 10% margin for response


@dataclass
class CompactionResult:
    """Result of a compaction operation.

    Attributes:
        original_tokens: Estimated tokens before compaction
        compacted_tokens: Estimated tokens after compaction
        messages_removed: Number of messages removed/summarized
        messages_preserved: Number of messages preserved
        strategy_used: Strategy that was applied
        summary: Generated summary (if summary strategy used)
    """

    original_tokens: int
    compacted_tokens: int
    messages_removed: int
    messages_preserved: int
    strategy_used: CompactionStrategy
    summary: str | None = None


COMPACT_PROMPT = """You are tasked with compacting a coding conversation context. This is critical for maintaining an effective working memory.

**Compression Rules:**
- MUST KEEP: Error messages, working solutions, current task state, file paths
- MERGE: Similar discussions into single summary
- REMOVE: Redundant explanations, failed attempts (keep lessons learned)
- CONDENSE: Long code/file content → keep key parts, signatures, and structure only
- PRESERVE: Any information that would be needed to continue the current task

**Input Context ({token_count} tokens):**

{context}

**Output a concise summary (aim for {target_tokens} tokens) in this structure:**

<current_task>
[What we're working on now - be specific about files and goals]
</current_task>

<completed>
- [Task]: [Brief outcome + key changes made]
</completed>

<code_state>
[Key files and their current state - signatures + key logic only]
[Include file paths that were modified]
</code_state>

<important>
[Any crucial context: errors, decisions made, constraints, blockers]
</important>
"""


def get_model_context_window(model: str, provider_id: str | None = None) -> int:
    """Get the context window size for a model.

    This function checks multiple sources in order:
    1. Models database cache (from models.dev)
    2. Built-in MODEL_CONTEXT_WINDOWS dictionary
    3. Pattern-based heuristics
    4. Default fallback (32K)

    Args:
        model: Model name or identifier
        provider_id: Optional provider ID for more accurate lookup

    Returns:
        Context window size in tokens
    """
    # First, try to get from models database
    try:
        from .models_db import get_context_window_from_database

        db_result = get_context_window_from_database(model, provider_id)
        if db_result != DEFAULT_CONTEXT_WINDOW:
            return db_result
    except ImportError:
        pass  # models_db not available
    except Exception as e:
        logger.debug(f"Failed to get context window from database: {e}")

    # Exact match in built-in
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]

    # Try partial matching (e.g., "gpt-4-turbo-2024-01-25" -> "gpt-4-turbo")
    # Sort by length (longest first) to prefer more specific matches
    model_lower = model.lower()
    sorted_models = sorted(MODEL_CONTEXT_WINDOWS.keys(), key=len, reverse=True)
    for known_model in sorted_models:
        if known_model in model_lower or model_lower.startswith(known_model):
            return MODEL_CONTEXT_WINDOWS[known_model]

    # Check for common patterns
    if "gpt-4" in model_lower:
        if "turbo" in model_lower or "4o" in model_lower:
            return 128_000
        if "32k" in model_lower:
            return 32_768
        return 8_192

    if "claude" in model_lower:
        return 200_000

    if "gemini" in model_lower:
        return 1_000_000

    if "deepseek" in model_lower:
        return 64_000

    if "qwen" in model_lower or "glm" in model_lower:
        return 128_000

    if "mistral" in model_lower or "mixtral" in model_lower:
        return 32_000

    if "llama" in model_lower:
        return 128_000

    logger.warning(f"Unknown model '{model}', using default context window of {DEFAULT_CONTEXT_WINDOW}")
    return DEFAULT_CONTEXT_WINDOW


def estimate_tokens(messages: list[dict[str, Any]], use_tiktoken: bool = True) -> int:
    """Estimate token count for messages.

    Args:
        messages: List of message dictionaries
        use_tiktoken: Try to use tiktoken for more accurate estimation

    Returns:
        Estimated token count
    """
    if use_tiktoken:
        try:
            import tiktoken

            # Use cl100k_base encoding (GPT-4, Claude compatible)
            enc = tiktoken.get_encoding("cl100k_base")
            total = 0
            for msg in messages:
                # Count role token overhead
                total += 4  # <|im_start|>role<|im_sep|>...<|im_end|>

                content = msg.get("content", "")
                if isinstance(content, str):
                    total += len(enc.encode(content))
                elif isinstance(content, list):
                    # Handle multi-modal content
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            total += len(enc.encode(item["text"]))

                # Count tool calls
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        if isinstance(tc, dict):
                            name = tc.get("name", "") or tc.get("function", {}).get("name", "")
                            args = tc.get("arguments", "") or tc.get("function", {}).get("arguments", "")
                            total += len(enc.encode(name)) + len(enc.encode(args))

            return total
        except ImportError:
            pass

    # Fallback: rough estimation (4 chars ≈ 1 token)
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content) // 4
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    total += len(item["text"]) // 4

        # Estimate tool calls
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict):
                    total += 50  # Overhead per tool call
                    args = tc.get("arguments", "") or tc.get("function", {}).get("arguments", "")
                    total += len(str(args)) // 4

    return total


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    """Convert messages to text for compaction."""
    parts = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if isinstance(content, str) and content.strip():
            parts.append(f"## Message {i + 1} ({role})\n{content}")

        # Include tool calls
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                name = tc.get("name", "") or tc.get("function", {}).get("name", "")
                args = tc.get("arguments", "") or tc.get("function", {}).get("arguments", "")
                parts.append(f"[Tool call: {name}]\nArgs: {args[:500]}...")

    return "\n\n".join(parts)


class SmartCompactor:
    """Smart context compaction with dynamic thresholds.

    This compactor automatically adjusts its behavior based on the model's
    context window size, ensuring optimal use of available context while
    preventing overflow.

    Example:
        compactor = SmartCompactor(client, model="gpt-4-turbo")

        # Automatic threshold calculation
        print(f"Using threshold: {compactor.threshold_tokens} tokens")

        if compactor.should_compact(messages):
            result = compactor.compact(messages)
            print(f"Reduced from {result.original_tokens} to {result.compacted_tokens}")
    """

    def __init__(
        self,
        client: OpenAI,
        model: str,
        config: CompactionConfig | None = None,
    ):
        """Initialize the smart compactor.

        Args:
            client: OpenAI client for generating summaries
            model: Model name for context window detection
            config: Optional compaction configuration
        """
        self.client = client
        self.model = model
        self.config = config or CompactionConfig()

        # Calculate dynamic thresholds
        self.context_window = get_model_context_window(model)
        self._update_thresholds()

        logger.info(
            f"SmartCompactor initialized for {model}: "
            f"context={self.context_window}, threshold={self.threshold_tokens}, "
            f"target={self.target_tokens}"
        )

    def _update_thresholds(self) -> None:
        """Update threshold values based on context window and config."""
        # Calculate available tokens (minus safety margin for response)
        available = int(self.context_window * (1 - self.config.safety_margin))

        # Threshold: when to trigger compaction
        self.threshold_tokens = int(available * self.config.threshold_ratio)

        # Target: what to aim for after compaction
        self.target_tokens = int(available * self.config.target_ratio)

        # Ensure target is reasonable
        self.target_tokens = max(self.target_tokens, self.config.min_tokens_to_compact)

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        """Check if compaction is needed.

        Args:
            messages: Current message history

        Returns:
            True if compaction should be triggered
        """
        current_tokens = estimate_tokens(messages)

        # Don't compact tiny contexts
        if current_tokens < self.config.min_tokens_to_compact:
            return False

        return current_tokens > self.threshold_tokens

    def get_token_usage(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Get detailed token usage information.

        Args:
            messages: Current message history

        Returns:
            Dictionary with usage statistics
        """
        current = estimate_tokens(messages)
        return {
            "current_tokens": current,
            "context_window": self.context_window,
            "threshold_tokens": self.threshold_tokens,
            "target_tokens": self.target_tokens,
            "usage_ratio": current / self.context_window,
            "should_compact": current > self.threshold_tokens,
            "headroom_tokens": self.context_window - current,
        }

    def compact(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], CompactionResult]:
        """Compact messages using the configured strategy.

        Args:
            messages: Messages to compact

        Returns:
            Tuple of (compacted_messages, result)
        """
        if not messages:
            return messages, CompactionResult(
                original_tokens=0,
                compacted_tokens=0,
                messages_removed=0,
                messages_preserved=0,
                strategy_used=self.config.strategy,
            )

        original_tokens = estimate_tokens(messages)

        # Find split point for preserved messages
        preserve_idx, to_compact, to_preserve = self._split_messages(messages)

        if not to_compact:
            return messages, CompactionResult(
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
                messages_removed=0,
                messages_preserved=len(messages),
                strategy_used=self.config.strategy,
            )

        # Apply compaction strategy
        strategy = self.config.strategy
        if strategy == CompactionStrategy.TRUNCATE:
            compacted, summary = self._truncate(to_compact)
        elif strategy == CompactionStrategy.SLIDING_WINDOW:
            compacted, summary = self._sliding_window(to_compact)
        elif strategy == CompactionStrategy.HYBRID:
            compacted, summary = self._hybrid(to_compact)
        else:  # SUMMARY (default)
            compacted, summary = self._summarize(to_compact)

        # Build final message list
        result_messages = compacted + to_preserve
        compacted_tokens = estimate_tokens(result_messages)

        # Emit event
        self._emit_compaction_event(
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            messages_removed=len(to_compact),
            strategy=strategy,
        )

        result = CompactionResult(
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            messages_removed=len(to_compact),
            messages_preserved=len(to_preserve) + len(compacted),
            strategy_used=strategy,
            summary=summary,
        )

        logger.info(
            f"Compacted context: {original_tokens} -> {compacted_tokens} tokens "
            f"({len(to_compact)} messages summarized, {len(to_preserve)} preserved)"
        )

        return result_messages, result

    def _split_messages(self, messages: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
        """Split messages into to_compact and to_preserve.

        Args:
            messages: All messages

        Returns:
            Tuple of (split_index, to_compact, to_preserve)
        """
        # Find split point - preserve last N user/assistant messages
        preserve_idx = len(messages)
        user_assistant_count = 0

        for i in range(len(messages) - 1, -1, -1):
            role = messages[i].get("role")
            if role in ("user", "assistant"):
                user_assistant_count += 1
                if user_assistant_count >= self.config.preserve_last:
                    preserve_idx = i
                    break

        # Also preserve recent tool results if configured
        if self.config.preserve_tool_results:
            tool_count = 0
            for i in range(preserve_idx - 1, -1, -1):
                if messages[i].get("role") == "tool":
                    tool_count += 1
                    if tool_count <= self.config.max_tool_results:
                        preserve_idx = i
                    else:
                        break

        to_compact = messages[:preserve_idx]
        to_preserve = messages[preserve_idx:]

        return preserve_idx, to_compact, to_preserve

    def _summarize(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        """Summarize old messages using LLM.

        Args:
            messages: Messages to summarize

        Returns:
            Tuple of (compacted_messages, summary_text)
        """
        context_text = _messages_to_text(messages)
        token_count = estimate_tokens(messages)

        prompt = COMPACT_PROMPT.format(
            token_count=token_count,
            context=context_text,
            target_tokens=self.target_tokens,
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that compacts conversation context for coding tasks.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=min(4000, self.target_tokens),
                temperature=0.3,  # Lower temperature for consistent summaries
            )
            summary = resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning(f"LLM summarization failed: {e}, falling back to truncation")
            return self._truncate(messages)

        compacted = [
            {
                "role": "assistant",
                "content": f"[Previous context compacted - {len(messages)} messages summarized]\n\n{summary}",
            }
        ]
        return compacted, summary

    def _truncate(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        """Simple truncation strategy.

        Args:
            messages: Messages to truncate

        Returns:
            Tuple of (truncated_messages, summary_text)
        """
        # Keep first and last few messages
        if len(messages) <= 4:
            return messages, ""

        first = messages[:2]
        last = messages[-2:]
        removed_count = len(messages) - 4

        summary = f"[... {removed_count} messages truncated ...]"
        result = first + [{"role": "assistant", "content": summary}] + last

        return result, summary

    def _sliding_window(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        """Sliding window strategy - keep most recent messages.

        Args:
            messages: Messages to process

        Returns:
            Tuple of (windowed_messages, summary_text)
        """
        # Calculate how many messages to keep
        target = self.target_tokens
        kept = []
        total_tokens = 0

        for msg in reversed(messages):
            msg_tokens = estimate_tokens([msg])
            if total_tokens + msg_tokens > target:
                break
            kept.insert(0, msg)
            total_tokens += msg_tokens

        removed_count = len(messages) - len(kept)
        if removed_count > 0:
            summary = f"[... {removed_count} older messages removed ...]"
            kept.insert(0, {"role": "assistant", "content": summary})
        else:
            summary = ""

        return kept, summary

    def _hybrid(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        """Hybrid strategy - sliding window with summary of removed content.

        Args:
            messages: Messages to process

        Returns:
            Tuple of (compacted_messages, summary_text)
        """
        # First apply sliding window to get recent messages
        target = self.target_tokens // 2  # Leave room for summary
        kept = []
        total_tokens = 0

        for msg in reversed(messages):
            msg_tokens = estimate_tokens([msg])
            if total_tokens + msg_tokens > target:
                break
            kept.insert(0, msg)
            total_tokens += msg_tokens

        removed = messages[: len(messages) - len(kept)]

        if not removed:
            return kept, ""

        # Summarize removed messages
        try:
            context = _messages_to_text(removed)
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Summarize this conversation context in 2-3 paragraphs."},
                    {"role": "user", "content": context[:10000]},  # Limit input
                ],
                max_tokens=500,
                temperature=0.3,
            )
            summary = resp.choices[0].message.content or ""
        except Exception:
            summary = f"[{len(removed)} older messages summarized]"

        result = [{"role": "assistant", "content": f"[Earlier context summary]\n{summary}"}] + kept
        return result, summary

    def _emit_compaction_event(
        self,
        original_tokens: int,
        compacted_tokens: int,
        messages_removed: int,
        strategy: CompactionStrategy,
    ) -> None:
        """Emit compaction event to event bus."""
        try:
            from .event_bus import Event, EventType, get_event_bus

            event = Event(
                type=EventType.CONTEXT_COMPACTED,
                source="compactor",
                data={
                    "original_tokens": original_tokens,
                    "compacted_tokens": compacted_tokens,
                    "messages_removed": messages_removed,
                    "strategy": strategy.value,
                    "model": self.model,
                    "context_window": self.context_window,
                    "threshold_tokens": self.threshold_tokens,
                },
            )
            get_event_bus().emit_sync(event)
        except Exception:
            pass  # Don't fail compaction if event emission fails


# Backward compatibility alias
Compactor = SmartCompactor


def create_compactor(
    client: OpenAI,
    model: str,
    strategy: str = "summary",
    threshold_ratio: float = 0.7,
    target_ratio: float = 0.3,
) -> SmartCompactor:
    """Create a smart compactor with custom settings.

    Args:
        client: OpenAI client
        model: Model name
        strategy: Compaction strategy ("summary", "truncate", "sliding_window", "hybrid")
        threshold_ratio: When to trigger compaction (ratio of context window)
        target_ratio: Target size after compaction

    Returns:
        Configured SmartCompactor instance
    """
    strategy_enum = {
        "summary": CompactionStrategy.SUMMARY,
        "truncate": CompactionStrategy.TRUNCATE,
        "sliding_window": CompactionStrategy.SLIDING_WINDOW,
        "hybrid": CompactionStrategy.HYBRID,
    }.get(strategy, CompactionStrategy.SUMMARY)

    config = CompactionConfig(
        strategy=strategy_enum,
        threshold_ratio=threshold_ratio,
        target_ratio=target_ratio,
    )

    return SmartCompactor(client, model, config)
