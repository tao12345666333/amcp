"""Prompt Manager for AMCP.

Handles loading, rendering, and caching of prompt templates with support for:
- Template variables and conditional sections
- Model-specific prompt variations
- Dynamic context injection
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from string import Template
from typing import Any


class ModelFamily(Enum):
    """Supported model families with specific optimizations."""

    ANTHROPIC = "anthropic"  # Claude models
    OPENAI = "openai"  # GPT models
    GEMINI = "gemini"  # Google Gemini models
    QWEN = "qwen"  # Alibaba Qwen models
    DEEPSEEK = "deepseek"  # DeepSeek models
    DEFAULT = "default"  # Generic fallback


@dataclass
class PromptContext:
    """Context data for prompt template rendering.

    Attributes:
        working_dir: Current working directory
        platform: Operating system platform
        date: Current date string
        time: Current time string
        is_git_repo: Whether working directory is a git repository
        git_branch: Current git branch name
        git_status: Git status summary
        git_recent_commits: Recent commit messages
        available_tools: List of available tool names
        skills_xml: XML representation of available skills
        memory_files: List of memory/context files content
        model_family: Target model family for optimization
        custom_vars: Additional custom template variables
    """

    working_dir: str = ""
    platform: str = ""
    date: str = ""
    time: str = ""
    is_git_repo: bool = False
    git_branch: str = ""
    git_status: str = ""
    git_recent_commits: str = ""
    available_tools: list[str] = field(default_factory=list)
    skills_xml: str = ""
    memory_files: list[dict[str, str]] = field(default_factory=list)
    model_family: ModelFamily = ModelFamily.DEFAULT
    custom_vars: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_environment(
        cls,
        working_dir: str | None = None,
        model_name: str = "",
        available_tools: list[str] | None = None,
        skills_xml: str = "",
        memory_files: list[dict[str, str]] | None = None,
    ) -> PromptContext:
        """Create context from current environment.

        Args:
            working_dir: Working directory (defaults to cwd)
            model_name: Model name to detect family
            available_tools: List of available tools
            skills_xml: Skills XML string
            memory_files: List of memory file dicts with path and content

        Returns:
            PromptContext with environment data
        """
        import platform

        work_dir = working_dir or os.getcwd()
        now = datetime.now()

        ctx = cls(
            working_dir=work_dir,
            platform=platform.system().lower(),
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"),
            available_tools=available_tools or [],
            skills_xml=skills_xml,
            memory_files=memory_files or [],
            model_family=cls._detect_model_family(model_name),
        )

        # Detect git information
        ctx._populate_git_info(work_dir)

        return ctx

    @staticmethod
    def _detect_model_family(model_name: str) -> ModelFamily:
        """Detect model family from model name."""
        model_lower = model_name.lower()

        if any(x in model_lower for x in ["claude", "anthropic"]):
            return ModelFamily.ANTHROPIC
        elif any(x in model_lower for x in ["gpt", "o1", "o3", "openai"]):
            return ModelFamily.OPENAI
        elif any(x in model_lower for x in ["gemini", "palm"]):
            return ModelFamily.GEMINI
        elif "qwen" in model_lower:
            return ModelFamily.QWEN
        elif "deepseek" in model_lower:
            return ModelFamily.DEEPSEEK
        else:
            return ModelFamily.DEFAULT

    def _populate_git_info(self, work_dir: str) -> None:
        """Populate git-related context fields."""
        git_dir = Path(work_dir) / ".git"
        self.is_git_repo = git_dir.exists()

        if not self.is_git_repo:
            return

        try:
            # Get current branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                self.git_branch = result.stdout.strip()

            # Get status summary
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                status = result.stdout.strip()
                if status:
                    # Limit to first 20 lines
                    lines = status.split("\n")[:20]
                    self.git_status = "\n".join(lines)
                else:
                    self.git_status = "clean"

            # Get recent commits
            result = subprocess.run(
                ["git", "log", "--oneline", "-n", "3"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                self.git_recent_commits = result.stdout.strip()

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass


class PromptManager:
    """Manager for loading and rendering prompt templates.

    Supports:
    - Loading templates from files or strings
    - Model-specific template variations
    - Dynamic variable substitution
    - Conditional section rendering
    """

    def __init__(self, templates_dir: Path | None = None):
        """Initialize prompt manager.

        Args:
            templates_dir: Directory containing template files
        """
        if templates_dir is None:
            templates_dir = Path(__file__).parent / "templates"
        self.templates_dir = templates_dir
        self._cache: dict[str, str] = {}

    def get_system_prompt(
        self,
        context: PromptContext,
        template_name: str = "coder",
    ) -> str:
        """Get rendered system prompt for the given context.

        Args:
            context: Prompt context with environment data
            template_name: Name of the template to use

        Returns:
            Rendered system prompt string
        """
        # Try model-specific template first
        model_template = f"{template_name}_{context.model_family.value}"
        template_content = self._load_template(model_template)

        # Fall back to generic template
        if not template_content:
            template_content = self._load_template(template_name)

        if not template_content:
            # Use default built-in template
            template_content = self._get_default_template()

        return self._render_template(template_content, context)

    def _load_template(self, name: str) -> str | None:
        """Load template from file.

        Args:
            name: Template name (without extension)

        Returns:
            Template content or None if not found
        """
        if name in self._cache:
            return self._cache[name]

        # Try .md.tpl first, then .md, then .txt
        for ext in [".md.tpl", ".md", ".txt"]:
            template_path = self.templates_dir / f"{name}{ext}"
            if template_path.exists():
                content = template_path.read_text(encoding="utf-8")
                self._cache[name] = content
                return content

        return None

    def _render_template(self, template: str, context: PromptContext) -> str:
        """Render template with context variables.

        Args:
            template: Template string
            context: Prompt context

        Returns:
            Rendered template string
        """
        # Build variables dict
        variables = {
            "working_dir": context.working_dir,
            "platform": context.platform,
            "date": context.date,
            "time": context.time,
            "is_git_repo": "yes" if context.is_git_repo else "no",
            "git_branch": context.git_branch,
            "git_status": context.git_status,
            "git_recent_commits": context.git_recent_commits,
            "available_tools": ", ".join(context.available_tools),
            "tools_list": self._format_tools_list(context.available_tools),
        }

        # Add custom variables
        variables.update(context.custom_vars)

        # Process conditional sections
        rendered = self._process_conditionals(template, context)

        # Render skills section
        if context.skills_xml:
            rendered = rendered.replace("${skills_section}", context.skills_xml)
        else:
            # Remove skills section placeholder and related text
            rendered = self._remove_section(rendered, "skills_section")

        # Render memory files section
        if context.memory_files:
            memory_content = self._format_memory_files(context.memory_files)
            rendered = rendered.replace("${memory_section}", memory_content)
        else:
            rendered = self._remove_section(rendered, "memory_section")

        # Substitute variables using safe substitution
        try:
            tmpl = Template(rendered)
            rendered = tmpl.safe_substitute(variables)
        except Exception:
            pass

        return rendered.strip()

    def _process_conditionals(self, template: str, context: PromptContext) -> str:
        """Process conditional sections in template.

        Supports:
        - {{if is_git_repo}}...{{end}}
        - {{if skills}}...{{end}}
        - {{if memory}}...{{end}}
        """
        import re

        result = template

        # Process git repo conditional
        git_pattern = r"\{\{if is_git_repo\}\}(.*?)\{\{end\}\}"
        if context.is_git_repo:
            result = re.sub(git_pattern, r"\1", result, flags=re.DOTALL)
        else:
            result = re.sub(git_pattern, "", result, flags=re.DOTALL)

        # Process skills conditional
        skills_pattern = r"\{\{if skills\}\}(.*?)\{\{end\}\}"
        if context.skills_xml:
            result = re.sub(skills_pattern, r"\1", result, flags=re.DOTALL)
        else:
            result = re.sub(skills_pattern, "", result, flags=re.DOTALL)

        # Process memory conditional
        memory_pattern = r"\{\{if memory\}\}(.*?)\{\{end\}\}"
        if context.memory_files:
            result = re.sub(memory_pattern, r"\1", result, flags=re.DOTALL)
        else:
            result = re.sub(memory_pattern, "", result, flags=re.DOTALL)

        return result

    def _remove_section(self, template: str, section_name: str) -> str:
        """Remove a section placeholder and surrounding newlines."""
        import re

        pattern = rf"\n*\$\{{{section_name}\}}\n*"
        return re.sub(pattern, "\n", template)

    def _format_tools_list(self, tools: list[str]) -> str:
        """Format tools as a bullet list."""
        if not tools:
            return "No tools available"
        return "\n".join(f"- {tool}" for tool in tools)

    def _format_memory_files(self, files: list[dict[str, str]]) -> str:
        """Format memory files as XML."""
        if not files:
            return ""

        lines = ["<memory>"]
        for f in files:
            path = f.get("path", "unknown")
            content = f.get("content", "")
            lines.append(f'<file path="{path}">')
            lines.append(content)
            lines.append("</file>")
        lines.append("</memory>")

        return "\n".join(lines)

    def _get_default_template(self) -> str:
        """Get the default built-in template."""
        return DEFAULT_CODER_TEMPLATE


# Global prompt manager instance
_prompt_manager: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    """Get the global prompt manager instance."""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


# Default template when no file is found
DEFAULT_CODER_TEMPLATE = """You are AMCP, a powerful AI coding agent that runs in the CLI.

<critical_rules>
These rules override everything else. Follow them strictly:

1. **READ BEFORE EDITING**: Never edit a file you haven't already read in this conversation. Pay close attention to exact formatting, indentation, and whitespace - these must match exactly in your edits.
2. **BE AUTONOMOUS**: Don't ask questions when you can search, read, think, decide, and act. Break complex tasks into steps and complete them all. Only stop for actual blocking errors.
3. **TEST AFTER CHANGES**: Run tests immediately after each modification when applicable.
4. **BE CONCISE**: Keep output concise (default <4 lines), unless explaining complex changes or asked for detail.
5. **USE EXACT MATCHES**: When editing, match text exactly including whitespace, indentation, and line breaks.
6. **NEVER COMMIT**: Unless user explicitly says "commit".
7. **FOLLOW PROJECT RULES**: If AGENTS.md or similar files contain specific instructions, you MUST follow them.
8. **SECURITY FIRST**: Only assist with defensive security tasks. Never expose secrets or API keys.
</critical_rules>

<communication_style>
Keep responses minimal:
- Under 4 lines of text (tool use doesn't count)
- No preamble ("Here's...", "I'll...")
- No postamble ("Let me know...", "Hope this helps...")
- One-word answers when possible
- No emojis
- No explanations unless user asks
- Use rich Markdown formatting for multi-sentence answers
- Reference code locations with `file_path:line_number` format

Examples:
user: what is 2+2?
assistant: 4

user: which file has the auth logic?
assistant: src/auth.py:45-120
</communication_style>

<workflow>
For every task, follow this sequence internally (don't narrate it):

**Before acting**:
- Search codebase for relevant files
- Read files to understand current state
- Check for project-specific rules (AGENTS.md)
- Identify what needs to change
- Use `git log` and `git blame` for additional context when needed

**While acting**:
- Read entire relevant sections before editing
- Before editing: verify exact whitespace and indentation
- Use exact text for find/replace (include whitespace)
- Make one logical change at a time
- After each change: run tests if applicable
- If tests fail: fix immediately
- If edit fails: read more context, don't guess

**Before finishing**:
- Verify ENTIRE query is resolved (not just first step)
- Run lint/typecheck if available
- Keep response under 4 lines
</workflow>

<decision_making>
**Make decisions autonomously** - don't ask when you can:
- Search to find the answer
- Read files to see patterns
- Check similar code in the project
- Infer from context
- Try most likely approach

**Only stop/ask user if**:
- Truly ambiguous business requirement
- Multiple valid approaches with big tradeoffs
- Could cause data loss
- Actually blocked by external factors

**Never stop for**:
- Task seems too large (break it down)
- Multiple files to change (change them)
- Work will take many steps (do all the steps)
</decision_making>

<editing_files>
Critical: ALWAYS read files before editing them.

When using edit tools:
1. Read the file first - note the EXACT indentation (spaces vs tabs, count)
2. Copy the exact text including ALL whitespace, newlines, and indentation
3. Include 3-5 lines of context before and after the target
4. Verify your target text would appear exactly once in the file
5. If uncertain about whitespace, include more surrounding context

**If edit fails**:
- View the file again at the specific location
- Copy even more context
- Check for tabs vs spaces
- Never retry with guessed changes - get the exact text first
</editing_files>

<error_handling>
When errors occur:
1. Read complete error message
2. Understand root cause
3. Try different approach (don't repeat same action)
4. Search for similar code that works
5. Make targeted fix
6. Test to verify

Common errors:
- Import/Module → check paths, spelling, what exists
- Syntax → check brackets, indentation, typos
- Tests fail → read test, see what it expects
- File not found → use ls, check exact path
- Edit tool failure → view file again, copy exact text
</error_handling>

<tool_usage>
- Search before assuming
- Read files before editing
- Always use absolute paths for file operations
- Use the task tool for complex searches or multi-step operations
- Run tools in parallel when safe (no dependencies)
- Summarize tool output for user (they don't see raw output)

For bash commands:
- Briefly explain commands that modify the system
- Use `&` for background processes that won't stop on their own
- Avoid interactive commands - use non-interactive versions
- Combine related commands to save time
</tool_usage>

<env>
Working directory: ${working_dir}
Platform: ${platform}
Date: ${date}
Time: ${time}
Is git repo: ${is_git_repo}
{{if is_git_repo}}
Git branch: ${git_branch}
Git status: ${git_status}
Recent commits:
${git_recent_commits}
{{end}}
</env>

<available_tools>
${tools_list}
</available_tools>

{{if skills}}
${skills_section}

<skills_usage>
When a user task matches a skill's description, read the skill's SKILL.md file.
Skills are activated by reading their location path. Follow the skill's instructions.
</skills_usage>
{{end}}

{{if memory}}
${memory_section}
{{end}}
"""
