from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .context_budget import estimate_text_tokens
from .relevance import RelevanceScorer, ToolTier
from .usage_tracker import ToolUsageSnapshot


@dataclass
class ToolSelectionResult:
    """Selected tools and metadata."""

    selected_tools: list[dict[str, Any]]
    hidden_count: int
    excluded_tools: list[str]


DEFAULT_TOOL_TIERS: dict[str, ToolTier] = {
    "read_file": ToolTier.ALWAYS,
    "grep": ToolTier.ALWAYS,
    "think": ToolTier.ALWAYS,
    "write_file": ToolTier.ALWAYS,
    "apply_patch": ToolTier.FREQUENT,
    "bash": ToolTier.FREQUENT,
    "todo": ToolTier.FREQUENT,
    "memory": ToolTier.ON_DEMAND,
    "task": ToolTier.ON_DEMAND,
}


class ProgressiveToolView:
    """Select tool specs dynamically by relevance and budget."""

    def __init__(self, scorer: RelevanceScorer):
        self.scorer = scorer

    def select_tools(
        self,
        *,
        tools: list[dict[str, Any]],
        user_input: str,
        conversation: list[dict[str, Any]],
        usage: ToolUsageSnapshot,
        budget_tokens: int,
        relevance_threshold: float,
        tier_overrides: dict[str, str] | None = None,
    ) -> ToolSelectionResult:
        tier_overrides = tier_overrides or {}
        conversation_text = "\n".join(str(m.get("content", "")) for m in conversation)

        tool_map = {self._tool_name(spec): spec for spec in tools if self._tool_name(spec)}
        relevant_tools = self._find_explicit_tool_mentions(user_input, set(tool_map.keys()))

        always: list[dict[str, Any]] = []
        candidates: list[tuple[dict[str, Any], float]] = []
        excluded: list[str] = []

        for spec in tools:
            name = self._tool_name(spec)
            if not name:
                continue

            tier = self._resolve_tier(name, tier_overrides)
            if tier == ToolTier.HIDDEN:
                excluded.append(name)
                continue

            if tier == ToolTier.ALWAYS:
                always.append(spec)
                continue

            score = self.scorer.score_tool(
                tool_name=name,
                tool_description=self._tool_description(spec),
                user_input=user_input,
                conversation_text=conversation_text,
                usage=usage,
                relevant_tools=relevant_tools,
            )

            if name in relevant_tools:
                score = 1.0
            elif tier == ToolTier.FREQUENT:
                score = min(score + 0.10, 1.0)

            candidates.append((spec, score))

        selected = list(always)
        remaining_budget = max(budget_tokens - self._estimate_specs_tokens(always), 0)

        candidates.sort(key=lambda item: item[1], reverse=True)
        for spec, score in candidates:
            if score < relevance_threshold:
                excluded.append(self._tool_name(spec))
                continue

            tool_tokens = self._estimate_spec_tokens(spec)
            if tool_tokens <= remaining_budget:
                selected.append(spec)
                remaining_budget -= tool_tokens
            else:
                excluded.append(self._tool_name(spec))

        hidden_count = max(len(tools) - len(selected), 0)
        return ToolSelectionResult(
            selected_tools=selected,
            hidden_count=hidden_count,
            excluded_tools=sorted({name for name in excluded if name}),
        )

    def _resolve_tier(self, tool_name: str, overrides: dict[str, str]) -> ToolTier:
        raw_override = overrides.get(tool_name) or (overrides.get("mcp.*") if tool_name.startswith("mcp.") else None)
        if raw_override:
            try:
                return ToolTier(raw_override)
            except ValueError:
                pass

        if tool_name.startswith("mcp."):
            return ToolTier.ON_DEMAND

        return DEFAULT_TOOL_TIERS.get(tool_name, ToolTier.ON_DEMAND)

    @staticmethod
    def _find_explicit_tool_mentions(user_input: str, tool_names: set[str]) -> set[str]:
        lower = user_input.lower()
        return {name for name in tool_names if name.lower() in lower}

    @staticmethod
    def _tool_name(spec: dict[str, Any]) -> str:
        return str(spec.get("function", {}).get("name", ""))

    @staticmethod
    def _tool_description(spec: dict[str, Any]) -> str:
        return str(spec.get("function", {}).get("description", ""))

    @staticmethod
    def _estimate_spec_tokens(spec: dict[str, Any]) -> int:
        payload = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
        return estimate_text_tokens(payload)

    def _estimate_specs_tokens(self, specs: list[dict[str, Any]]) -> int:
        return sum(self._estimate_spec_tokens(spec) for spec in specs)
