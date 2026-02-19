from __future__ import annotations

from dataclasses import dataclass

from ..compaction import get_model_context_window


@dataclass
class ContextBudget:
    """Token budget split for system prompt components."""

    total_available: int
    prompt_budget: int
    base_prompt: int
    tools: int
    skills: int
    memory: int
    rules: int
    buffer: int


@dataclass
class ContextBudgetDefaults:
    """Default knobs for context budget allocation."""

    response_ratio: float = 0.30
    min_prompt_budget: int = 2500
    base_prompt_max_tokens: int = 2200
    tool_budget_ratio: float = 0.45
    skill_budget_ratio: float = 0.30
    memory_budget_ratio: float = 0.15
    rules_budget_ratio: float = 0.10


class ContextBudgetManager:
    """Allocate token budget based on model window and conversation size."""

    def __init__(self, model: str, config: object | None = None):
        self.model_window = get_model_context_window(model)
        self.config = config or ContextBudgetDefaults()

    def calculate_budget(self, conversation_tokens: int) -> ContextBudget:
        response_ratio = self._clamp_ratio(getattr(self.config, "response_ratio", 0.30), default=0.30)
        response_reserve = int(self.model_window * response_ratio)

        available_for_prompt = self.model_window - response_reserve - max(conversation_tokens, 0)
        min_prompt_budget = int(max(getattr(self.config, "min_prompt_budget", 2500), 0))
        prompt_budget = max(available_for_prompt, min_prompt_budget)

        base_prompt = min(
            int(max(getattr(self.config, "base_prompt_max_tokens", 2200), 0)),
            prompt_budget,
        )

        allocatable = max(prompt_budget - base_prompt, 0)
        ratios = self._normalized_component_ratios()

        tools = int(allocatable * ratios["tools"])
        skills = int(allocatable * ratios["skills"])
        memory = int(allocatable * ratios["memory"])
        rules = int(allocatable * ratios["rules"])
        allocated = base_prompt + tools + skills + memory + rules
        buffer = max(prompt_budget - allocated, 0)

        return ContextBudget(
            total_available=self.model_window,
            prompt_budget=prompt_budget,
            base_prompt=base_prompt,
            tools=tools,
            skills=skills,
            memory=memory,
            rules=rules,
            buffer=buffer,
        )

    def _normalized_component_ratios(self) -> dict[str, float]:
        raw = {
            "tools": self._positive_ratio(getattr(self.config, "tool_budget_ratio", 0.45), 0.45),
            "skills": self._positive_ratio(getattr(self.config, "skill_budget_ratio", 0.30), 0.30),
            "memory": self._positive_ratio(getattr(self.config, "memory_budget_ratio", 0.15), 0.15),
            "rules": self._positive_ratio(getattr(self.config, "rules_budget_ratio", 0.10), 0.10),
        }
        total = sum(raw.values())
        if total <= 0:
            return {
                "tools": 0.45,
                "skills": 0.30,
                "memory": 0.15,
                "rules": 0.10,
            }
        return {name: value / total for name, value in raw.items()}

    @staticmethod
    def _clamp_ratio(value: object, default: float) -> float:
        try:
            ratio = float(value)
        except (TypeError, ValueError):
            return default
        return min(max(ratio, 0.0), 0.9)

    @staticmethod
    def _positive_ratio(value: object, default: float) -> float:
        try:
            ratio = float(value)
        except (TypeError, ValueError):
            return default
        return ratio if ratio > 0 else 0.0


def estimate_text_tokens(text: str) -> int:
    """Cheap approximation for plain-text token counting."""
    if not text:
        return 0
    return max(len(text) // 4, 1)
