"""Context compaction for reducing token usage."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

COMPACT_PROMPT = """You are tasked with compacting a coding conversation context. This is critical for maintaining an effective working memory.

**Compression Rules:**
- MUST KEEP: Error messages, working solutions, current task state
- MERGE: Similar discussions into single summary
- REMOVE: Redundant explanations, failed attempts (keep lessons learned)
- CONDENSE: Long code/file content → keep key parts only

**Input Context:**

{context}

**Output a concise summary in this structure:**

<current_task>
[What we're working on now]
</current_task>

<completed>
- [Task]: [Brief outcome]
</completed>

<code_state>
[Key files and their current state - signatures + key logic only]
</code_state>

<important>
[Any crucial context not covered above]
</important>
"""


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate (4 chars ≈ 1 token)."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content) // 4
    return total


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    """Convert messages to text for compaction."""
    parts = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            parts.append(f"## Message {i + 1} ({role})\n{content}")
    return "\n\n".join(parts)


class Compactor:
    """Compacts conversation history to reduce token usage."""

    # Trigger compaction when estimated tokens exceed this
    TOKEN_THRESHOLD = 50000
    # Keep last N user/assistant messages uncompacted
    PRESERVE_LAST = 4

    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        """Check if compaction is needed."""
        return _estimate_tokens(messages) > self.TOKEN_THRESHOLD

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compact messages, preserving recent ones."""
        if not messages:
            return messages

        # Find split point - preserve last N user/assistant messages
        preserve_idx = len(messages)
        count = 0
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") in ("user", "assistant"):
                count += 1
                if count >= self.PRESERVE_LAST:
                    preserve_idx = i
                    break

        if preserve_idx == 0:
            return messages  # Nothing to compact

        to_compact = messages[:preserve_idx]
        to_preserve = messages[preserve_idx:]

        if not to_compact:
            return to_preserve

        # Compact old messages
        context_text = _messages_to_text(to_compact)
        prompt = COMPACT_PROMPT.format(context=context_text)

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that compacts conversation context."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2000,
            )
            summary = resp.choices[0].message.content or ""
        except Exception:
            # On failure, just truncate
            summary = context_text[:4000] + "\n... [truncated]"

        # Build compacted history
        compacted = [
            {
                "role": "assistant",
                "content": f"[Previous context compacted]\n{summary}",
            }
        ]
        compacted.extend(to_preserve)
        return compacted
