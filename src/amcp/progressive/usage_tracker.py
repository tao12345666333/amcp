from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import exp
from typing import Any


@dataclass
class ToolUsageSnapshot:
    """Computed usage snapshot from tool call history."""

    call_counts: dict[str, int] = field(default_factory=dict)
    last_used: dict[str, datetime] = field(default_factory=dict)
    cooccurrence_counts: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def total_calls(self) -> int:
        return sum(self.call_counts.values())


class ToolUsageTracker:
    """Build usage statistics from in-memory tool history."""

    @staticmethod
    def from_history(history: list[dict[str, Any]]) -> ToolUsageSnapshot:
        snapshot = ToolUsageSnapshot()

        ordered = sorted(
            history,
            key=lambda item: item.get("timestamp") or "",
        )

        prev_tool: str | None = None
        for entry in ordered:
            tool_name = str(entry.get("tool") or "").strip()
            if not tool_name:
                continue

            snapshot.call_counts[tool_name] = snapshot.call_counts.get(tool_name, 0) + 1

            timestamp = ToolUsageTracker._parse_timestamp(entry.get("timestamp"))
            if timestamp:
                current = snapshot.last_used.get(tool_name)
                if current is None or timestamp > current:
                    snapshot.last_used[tool_name] = timestamp

            if prev_tool and prev_tool != tool_name:
                pair = tuple(sorted((prev_tool, tool_name)))
                snapshot.cooccurrence_counts[pair] = snapshot.cooccurrence_counts.get(pair, 0) + 1

            prev_tool = tool_name

        return snapshot

    @staticmethod
    def recency_score(
        snapshot: ToolUsageSnapshot,
        tool_name: str,
        *,
        now: datetime | None = None,
        half_life_seconds: int = 600,
    ) -> float:
        last_used = snapshot.last_used.get(tool_name)
        if not last_used:
            return 0.0

        now_dt = now or datetime.now()
        age = max((now_dt - last_used).total_seconds(), 0)
        if half_life_seconds <= 0:
            return 0.0
        decay = exp(-age / half_life_seconds)
        return max(0.0, min(decay, 1.0))

    @staticmethod
    def frequency_score(snapshot: ToolUsageSnapshot, tool_name: str) -> float:
        calls = snapshot.call_counts.get(tool_name, 0)
        if calls <= 0:
            return 0.0
        max_calls = max(snapshot.call_counts.values(), default=1)
        return min(calls / max_calls, 1.0)

    @staticmethod
    def cooccurrence_score(
        snapshot: ToolUsageSnapshot,
        tool_name: str,
        relevant_tools: set[str],
    ) -> float:
        if not relevant_tools:
            return 0.0

        score = 0
        max_pair_count = max(snapshot.cooccurrence_counts.values(), default=1)
        for other in relevant_tools:
            if other == tool_name:
                continue
            pair = tuple(sorted((tool_name, other)))
            score += snapshot.cooccurrence_counts.get(pair, 0)

        if score <= 0:
            return 0.0
        return min(score / max_pair_count, 1.0)

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        if not value:
            return None
        text = str(value)
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
