from __future__ import annotations

from datetime import datetime, timedelta

from amcp.config import ContextConfig
from amcp.progressive.context_budget import ContextBudgetManager
from amcp.progressive.relevance import RelevanceScorer
from amcp.progressive.skill_view import ProgressiveSkillView
from amcp.progressive.tool_view import ProgressiveToolView
from amcp.progressive.usage_tracker import ToolUsageTracker
from amcp.skills import SkillMetadata


def _tool_spec(name: str, description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_context_budget_allocation_is_stable():
    cfg = ContextConfig(min_prompt_budget=1800)
    manager = ContextBudgetManager(model="unknown-model", config=cfg)
    budget = manager.calculate_budget(conversation_tokens=24000)

    assert budget.prompt_budget >= 1800
    allocated = budget.base_prompt + budget.tools + budget.skills + budget.memory + budget.rules + budget.buffer
    assert allocated == budget.prompt_budget


def test_progressive_tool_view_keeps_always_tools_and_respects_budget():
    scorer = RelevanceScorer()
    view = ProgressiveToolView(scorer)
    tools = [
        _tool_spec("read_file", "Read files from workspace"),
        _tool_spec("grep", "Search text patterns"),
        _tool_spec("think", "Internal planning"),
        _tool_spec("apply_patch", "Edit files with patch diffs"),
        _tool_spec("task", "Delegate work to subagents"),
    ]

    history = [
        {
            "tool": "apply_patch",
            "timestamp": (datetime.now() - timedelta(seconds=20)).isoformat(),
        }
    ]
    usage = ToolUsageTracker.from_history(history)

    result = view.select_tools(
        tools=tools,
        user_input="Implement a feature and modify existing code.",
        conversation=[],
        usage=usage,
        budget_tokens=120,
        relevance_threshold=0.2,
        tier_overrides={},
    )

    names = {t["function"]["name"] for t in result.selected_tools}
    assert {"read_file", "grep", "think"}.issubset(names)
    assert len(result.selected_tools) <= len(tools)


def test_progressive_skill_view_falls_back_when_budget_is_small():
    scorer = RelevanceScorer()
    view = ProgressiveSkillView(scorer)

    active = SkillMetadata(
        name="python-refactor",
        description="Refactor Python code safely",
        location="/tmp/skill/SKILL.md",
        body="# Steps\n" + "do detailed transformations\n" * 200,
    )
    secondary = SkillMetadata(
        name="ci-helper",
        description="Debug CI and flaky tests",
        location="/tmp/ci/SKILL.md",
        body="# Diagnose\nCollect failing logs",
    )

    result = view.build_prompt(
        skills=[active, secondary],
        user_input="Please refactor this module",
        active_skills={"python-refactor"},
        budget_tokens=45,
        relevance_threshold=0.2,
    )

    assert "python-refactor" in result.prompt
    assert "do detailed transformations" not in result.prompt
