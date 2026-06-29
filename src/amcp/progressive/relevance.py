from __future__ import annotations

import re
from enum import StrEnum

from .usage_tracker import ToolUsageSnapshot, ToolUsageTracker


class ToolTier(StrEnum):
    """Tool importance tiers."""

    ALWAYS = "always"
    FREQUENT = "frequent"
    ON_DEMAND = "on_demand"
    HIDDEN = "hidden"


class SkillLoadLevel(StrEnum):
    """Skill context load levels."""

    SUMMARY = "summary"
    OVERVIEW = "overview"
    FULL = "full"


TASK_PATTERNS: dict[str, set[str]] = {
    "implementation": {"implement", "create", "add", "build", "write", "develop"},
    "debugging": {"fix", "bug", "error", "failing", "broken", "debug"},
    "exploration": {"find", "search", "where", "show", "list", "locate"},
    "review": {"review", "diff", "pr", "pull", "analyze"},
    "automation": {"run", "command", "script", "shell", "bash", "test"},
}


TOOL_KEYWORDS: dict[str, set[str]] = {
    "read_file": {"read", "open", "content", "file", "source"},
    "grep": {"search", "grep", "find", "pattern", "regex"},
    "think": {"plan", "reason", "analyze", "think"},
    "web_search": {"web", "internet", "search", "docs", "documentation", "online", "current"},
    "web_fetch": {"web", "internet", "fetch", "url", "page", "website", "docs", "content"},
    "bash": {"run", "command", "shell", "execute", "build", "test"},
    "write_file": {"write", "create", "save", "generate", "overwrite"},
    "apply_patch": {"edit", "patch", "modify", "change", "update", "fix"},
    "todo": {"todo", "task", "plan", "checklist"},
    "task": {"parallel", "delegate", "subagent", "task"},
    "memory": {"remember", "history", "context", "memory"},
}


TASK_TOOL_AFFINITY: dict[str, set[str]] = {
    "implementation": {"read_file", "apply_patch", "write_file", "grep"},
    "debugging": {"read_file", "grep", "bash", "apply_patch"},
    "exploration": {"read_file", "grep", "web_search", "web_fetch"},
    "review": {"read_file", "grep", "think", "web_search", "web_fetch"},
    "automation": {"bash", "task", "todo", "memory"},
}


class RelevanceScorer:
    """Score tool and skill relevance for the current request."""

    def score_tool(
        self,
        *,
        tool_name: str,
        tool_description: str,
        user_input: str,
        conversation_text: str,
        usage: ToolUsageSnapshot,
        relevant_tools: set[str] | None = None,
    ) -> float:
        user_tokens = self._tokenize(user_input)
        context_tokens = user_tokens | self._tokenize(conversation_text)
        tool_tokens = TOOL_KEYWORDS.get(tool_name, set()) | self._tokenize(tool_description)

        keyword_score = self._overlap_score(tool_tokens, context_tokens)

        task_type = self.classify_task(user_input)
        affinity_tools = TASK_TOOL_AFFINITY.get(task_type, set())
        task_affinity = 1.0 if tool_name in affinity_tools else 0.0

        recency = ToolUsageTracker.recency_score(usage, tool_name)
        frequency = ToolUsageTracker.frequency_score(usage, tool_name)
        cooccurrence = ToolUsageTracker.cooccurrence_score(usage, tool_name, relevant_tools or set())

        score = keyword_score * 0.45 + task_affinity * 0.25 + recency * 0.15 + frequency * 0.10 + cooccurrence * 0.05
        return max(0.0, min(score, 1.0))

    def score_skill(
        self,
        *,
        skill_name: str,
        skill_description: str,
        user_input: str,
        active_skills: set[str],
    ) -> float:
        if skill_name in active_skills:
            return 1.0

        input_tokens = self._tokenize(user_input)
        skill_tokens = self._tokenize(skill_name) | self._tokenize(skill_description)
        overlap = self._overlap_score(skill_tokens, input_tokens)

        task_type = self.classify_task(user_input)
        task_boost = 0.2 if task_type in self._tokenize(skill_description) else 0.0
        score = overlap * 0.8 + task_boost
        return max(0.0, min(score, 1.0))

    def classify_task(self, user_input: str) -> str:
        tokens = self._tokenize(user_input)
        best_task = "general"
        best_score = 0
        for task, keywords in TASK_PATTERNS.items():
            overlap = len(tokens & keywords)
            if overlap > best_score:
                best_score = overlap
                best_task = task
        return best_task

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))

    @staticmethod
    def _overlap_score(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        overlap = len(a & b)
        return min(overlap / max(len(a), 1), 1.0)
