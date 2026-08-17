from __future__ import annotations

from dataclasses import dataclass

from ..skills import SkillMetadata
from .context_budget import estimate_text_tokens
from .relevance import RelevanceScorer


@dataclass
class SkillPromptResult:
    """Rendered skill prompt metadata."""

    prompt: str
    full_count: int
    overview_count: int
    summary_count: int


class ProgressiveSkillView:
    """Build skill prompt content using progressive detail levels."""

    def __init__(self, scorer: RelevanceScorer):
        self.scorer = scorer

    def build_prompt(
        self,
        *,
        skills: list[SkillMetadata],
        user_input: str,
        active_skills: set[str],
        budget_tokens: int,
        relevance_threshold: float,
    ) -> SkillPromptResult:
        if not skills or budget_tokens <= 0:
            return SkillPromptResult(prompt="", full_count=0, overview_count=0, summary_count=0)

        sections: list[str] = []
        remaining = budget_tokens
        full_count = 0
        overview_count = 0
        summary_count = 0

        skill_by_name = {skill.name: skill for skill in skills}

        for name in sorted(active_skills):
            skill = skill_by_name.get(name)
            if not skill:
                continue
            full = self._render_full(skill)
            full_tokens = estimate_text_tokens(full)
            if full_tokens <= remaining:
                sections.append(full)
                remaining -= full_tokens
                full_count += 1
            else:
                overview = self._render_overview(skill)
                overview_tokens = estimate_text_tokens(overview)
                if overview_tokens <= remaining:
                    sections.append(overview)
                    remaining -= overview_tokens
                    overview_count += 1
                else:
                    summary = self._render_summary(skill)
                    summary_tokens = estimate_text_tokens(summary)
                    if summary_tokens <= remaining:
                        sections.append(summary)
                        remaining -= summary_tokens
                        summary_count += 1

        scored: list[tuple[SkillMetadata, float]] = []
        for skill in skills:
            if skill.name in active_skills:
                continue
            # Skip explicit-only skills from auto-triggering unless explicitly activated
            if not skill.auto_trigger:
                continue
            score = self.scorer.score_skill(
                skill_name=skill.name,
                skill_description=skill.description,
                user_input=user_input,
                active_skills=active_skills,
            )
            scored.append((skill, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        included_names = {name for name in active_skills if name in skill_by_name}

        for skill, score in scored:
            if score < relevance_threshold:
                continue
            overview = self._render_overview(skill)
            tokens = estimate_text_tokens(overview)
            if tokens <= remaining:
                sections.append(overview)
                remaining -= tokens
                overview_count += 1
                included_names.add(skill.name)

        summary_lines: list[str] = []
        for skill in skills:
            if skill.name in included_names:
                continue
            line = self._render_summary(skill)
            summary_lines.append(line)

        if summary_lines:
            summary_block = "## Other Available Skills\n" + "\n".join(summary_lines)
            summary_tokens = estimate_text_tokens(summary_block)
            if summary_tokens <= remaining:
                sections.append(summary_block)
                summary_count += len(summary_lines)
            elif remaining > 0:
                partial: list[str] = ["## Other Available Skills"]
                for line in summary_lines:
                    new_tokens = estimate_text_tokens("\n".join(partial + [line]))
                    if new_tokens > remaining:
                        break
                    partial.append(line)
                if len(partial) > 1:
                    sections.append("\n".join(partial))
                    summary_count += len(partial) - 1

        prompt = "\n\n".join(s.strip() for s in sections if s.strip())
        return SkillPromptResult(
            prompt=prompt,
            full_count=full_count,
            overview_count=overview_count,
            summary_count=summary_count,
        )

    @staticmethod
    def _render_full(skill: SkillMetadata) -> str:
        return (
            f"## Active Skill: {skill.name}\n"
            f"*{skill.description}*\n\n"
            f"Location: `{skill.location}`\n\n"
            f"{skill.body.strip()}"
        )

    @staticmethod
    def _render_overview(skill: SkillMetadata) -> str:
        capability_lines = [
            line.strip("# ").strip() for line in skill.body.splitlines() if line.strip().startswith("#")
        ]
        capabilities = capability_lines[:3]
        section = [
            f"## Skill Overview: {skill.name}",
            skill.description,
            f"Location: `{skill.location}`",
        ]
        if capabilities:
            section.append("Capabilities:")
            section.extend(f"- {item}" for item in capabilities)
        return "\n".join(section)

    @staticmethod
    def _render_summary(skill: SkillMetadata) -> str:
        explicit_marker = " [explicit-only]" if not skill.auto_trigger else ""
        return f"- {skill.name}{explicit_marker}: {skill.description}"
