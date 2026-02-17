"""
Skills system for AMCP.

Skills are reusable knowledge or behavior definitions that can be activated
to provide specialized capabilities to the agent. They are defined as
markdown files with YAML frontmatter containing:
- name: The skill name
- description: A brief description of what the skill provides
- triggers (optional): Schedule or event triggers for autonomous execution

Skills are discovered from (in order of increasing precedence):
- Built-in skills: Bundled with AMCP (e.g., skill-creator)
- User skills: ~/.config/amcp/skills/<skill-name>/SKILL.md
- Project skills: .amcp/skills/<skill-name>/SKILL.md (highest precedence)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Regex to parse YAML frontmatter
FRONTMATTER_REGEX = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)", re.MULTILINE)

# Default config directory
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "amcp"


@dataclass
class SkillTrigger:
    """A trigger that causes a skill to execute autonomously.

    Supports two kinds:
    - **schedule**: cron expression (e.g. ``"*/15 * * * *"``, ``"@hourly"``)
    - **event**: event type string (e.g. ``"github.push"``, ``"github.pull_request.opened"``)

    Exactly one of ``schedule`` or ``event`` must be set.
    """

    command: str  # prompt to send to the agent
    schedule: str | None = None  # cron expression
    event: str | None = None  # event type string
    notify: bool = True
    timeout: int = 300
    work_dir: str | None = None


@dataclass
class SkillMetadata:
    """Metadata for a discovered skill."""

    name: str
    description: str
    location: str
    body: str
    disabled: bool = False
    triggers: list[SkillTrigger] = field(default_factory=list)


@dataclass
class SkillManager:
    """
    Manages the discovery and lifecycle of skills.

    Skills are discovered from three sources (lowest to highest precedence):
    - Built-in skills: Bundled with AMCP
    - User-level skills: ~/.config/amcp/skills/
    - Project-level skills: .amcp/skills/
    """

    _skills: list[SkillMetadata] = field(default_factory=list)
    _active_skill_names: set[str] = field(default_factory=set)
    _disabled_skill_names: set[str] = field(default_factory=set)

    @staticmethod
    def get_user_skills_dir() -> Path:
        """Get the user-level skills directory."""
        return CONFIG_DIR / "skills"

    @staticmethod
    def get_project_skills_dir(project_root: Path | None = None) -> Path:
        """Get the project-level skills directory."""
        root = project_root or Path.cwd()
        return root / ".amcp" / "skills"

    @staticmethod
    def get_agents_skills_dir(project_root: Path | None = None) -> Path:
        """Get the agents-level skills directory."""
        root = project_root or Path.cwd()
        return root / ".agents" / "skills"

    def clear_skills(self) -> None:
        """Clear all discovered skills."""
        self._skills = []

    @staticmethod
    def get_builtin_skills_dir() -> Path:
        """Get the built-in skills directory (bundled with AMCP)."""
        from .builtin_skills import BUILTIN_SKILLS_DIR

        return BUILTIN_SKILLS_DIR

    def discover_skills(self, project_root: Path | None = None) -> None:
        """
        Discover skills from all sources.

        Discovery order (lowest to highest precedence):
        1. Built-in skills (bundled with AMCP)
        2. User skills (~/.config/amcp/skills/)
        3. Agents skills (.agents/skills/)
        4. Project skills (.amcp/skills/) — highest precedence

        Args:
            project_root: The project root directory (defaults to cwd)
        """
        self.clear_skills()

        # Discover built-in skills first (lowest precedence)
        builtin_skills_dir = self.get_builtin_skills_dir()
        builtin_skills = self._discover_skills_from_dir(builtin_skills_dir)
        self._add_skills_with_precedence(builtin_skills)

        # Discover user skills (override built-in)
        user_skills_dir = self.get_user_skills_dir()
        user_skills = self._discover_skills_from_dir(user_skills_dir)
        self._add_skills_with_precedence(user_skills)

        # Discover agents skills (override user)
        agents_skills_dir = self.get_agents_skills_dir(project_root)
        agents_skills = self._discover_skills_from_dir(agents_skills_dir)
        self._add_skills_with_precedence(agents_skills)

        # Discover project skills (highest precedence)
        project_skills_dir = self.get_project_skills_dir(project_root)
        project_skills = self._discover_skills_from_dir(project_skills_dir)
        self._add_skills_with_precedence(project_skills)

    def _add_skills_with_precedence(self, new_skills: list[SkillMetadata]) -> None:
        """Add skills with name-based precedence (later skills override earlier)."""
        skill_map: dict[str, SkillMetadata] = {}
        for skill in self._skills + new_skills:
            skill_map[skill.name] = skill
        self._skills = list(skill_map.values())

    def _discover_skills_from_dir(self, skills_dir: Path) -> list[SkillMetadata]:
        """
        Discover skills from a directory.

        Each skill should be in a subdirectory with a SKILL.md file.

        Args:
            skills_dir: Directory to search for skills

        Returns:
            List of discovered skills
        """
        discovered: list[SkillMetadata] = []

        if not skills_dir.exists() or not skills_dir.is_dir():
            return discovered

        # Look for subdirectories containing SKILL.md
        for skill_folder in skills_dir.iterdir():
            if not skill_folder.is_dir():
                continue

            skill_file = skill_folder / "SKILL.md"
            if not skill_file.exists():
                continue

            skill = self._parse_skill_file(skill_file)
            if skill:
                discovered.append(skill)

        return discovered

    def _parse_skill_file(self, file_path: Path) -> SkillMetadata | None:
        """
        Parse a SKILL.md file and extract metadata.

        Args:
            file_path: Path to the SKILL.md file

        Returns:
            SkillMetadata if valid, None otherwise
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            match = FRONTMATTER_REGEX.match(content)

            if not match:
                return None

            frontmatter_text = match.group(1)
            body = match.group(2).strip()

            # Parse YAML frontmatter
            if yaml is None:
                # Fallback to simple parsing if PyYAML not available
                frontmatter = self._parse_simple_yaml(frontmatter_text)
            else:
                frontmatter = yaml.safe_load(frontmatter_text)

            if not frontmatter or not isinstance(frontmatter, dict):
                return None

            name = frontmatter.get("name")
            description = frontmatter.get("description", "")

            if not isinstance(name, str):
                return None

            # Parse triggers
            triggers = self._parse_triggers(frontmatter.get("triggers"))

            return SkillMetadata(
                name=name,
                description=description if isinstance(description, str) else "",
                location=str(file_path),
                body=body,
                disabled=name in self._disabled_skill_names,
                triggers=triggers,
            )
        except Exception:
            return None

    @staticmethod
    def _parse_triggers(raw: Any) -> list[SkillTrigger]:
        """Parse triggers from frontmatter."""
        if not raw or not isinstance(raw, list):
            return []
        triggers: list[SkillTrigger] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            command = item.get("command", "")
            if not command:
                continue
            triggers.append(
                SkillTrigger(
                    command=str(command),
                    schedule=str(item["schedule"]) if item.get("schedule") else None,
                    event=str(item["event"]) if item.get("event") else None,
                    notify=bool(item.get("notify", True)),
                    timeout=int(item.get("timeout", 300)),
                    work_dir=str(item["work_dir"]) if item.get("work_dir") else None,
                )
            )
        return triggers

    def _parse_simple_yaml(self, yaml_text: str) -> dict:
        """Simple YAML parser for name/description when PyYAML not available."""
        result = {}
        for line in yaml_text.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                result[key] = value
        return result

    def get_skills(self) -> list[SkillMetadata]:
        """Get all enabled skills."""
        return [s for s in self._skills if not s.disabled]

    def get_all_skills(self) -> list[SkillMetadata]:
        """Get all discovered skills, including disabled ones."""
        return self._skills

    def get_skill(self, name: str) -> SkillMetadata | None:
        """Get a skill by name."""
        for skill in self._skills:
            if skill.name == name:
                return skill
        return None

    def set_disabled_skills(self, disabled_names: list[str]) -> None:
        """Set the list of disabled skill names."""
        self._disabled_skill_names = set(disabled_names)
        for skill in self._skills:
            skill.disabled = skill.name in self._disabled_skill_names

    def activate_skill(self, name: str) -> bool:
        """
        Activate a skill by name.

        Args:
            name: The skill name to activate

        Returns:
            True if the skill was activated, False if not found or disabled
        """
        skill = self.get_skill(name)
        if skill and not skill.disabled:
            self._active_skill_names.add(name)
            return True
        return False

    def deactivate_skill(self, name: str) -> None:
        """Deactivate a skill by name."""
        self._active_skill_names.discard(name)

    def is_skill_active(self, name: str) -> bool:
        """Check if a skill is currently active."""
        return name in self._active_skill_names

    def get_active_skills(self) -> list[SkillMetadata]:
        """Get all currently active skills."""
        return [skill for skill in self._skills if skill.name in self._active_skill_names and not skill.disabled]

    def get_active_skills_content(self) -> str:
        """
        Get the content of all currently active skills combined.

        Returns:
            Combined skill content for injection into system prompt
        """
        active = self.get_active_skills()
        if not active:
            return ""

        # Format active skills as a section
        parts = []
        parts.append("\n## Active Skills\n")
        for skill in active:
            parts.append(f"### Skill: {skill.name}")
            parts.append(f"*{skill.description}*\n")
            parts.append(skill.body)
            parts.append("")

        return "\n".join(parts)

    def build_skills_summary(self) -> str:
        """
        Build a compact skills summary for the system prompt.

        This implements progressive disclosure: only a compact summary
        (name + description + location) is included in the system prompt. The full
        skill body is only loaded when the agent reads the skill file.

        Returns:
            Compact skills summary string, or empty string if no skills
        """
        skills = self.get_skills()
        if not skills:
            return ""

        lines = []
        lines.append("<skills>")
        lines.append(
            "You can use specialized 'skills' to help you with complex tasks. "
            "Each skill has a name, description, and location listed below."
        )
        lines.append("")
        lines.append(
            "Skills are folders of instructions, scripts, and resources that extend "
            "your capabilities for specialized tasks. Each skill folder contains:"
        )
        lines.append(
            "- **SKILL.md** (required): The main instruction file with YAML frontmatter "
            "(name, description) and detailed markdown instructions"
        )
        lines.append("")
        lines.append("More complex skills may include additional directories and files:")
        lines.append("- **scripts/** - Helper scripts and utilities")
        lines.append("- **references/** - Reference documentation")
        lines.append("- **assets/** - Templates and other files")
        lines.append("")
        lines.append(
            "If a skill seems relevant to your current task, you MUST use the `read_file` tool "
            "on the SKILL.md file to read its full instructions before proceeding. "
            "Once you have read the instructions, follow them exactly as documented."
        )
        lines.append("")

        # List skills with their status and location
        for skill in skills:
            active_marker = " ⭐" if self.is_skill_active(skill.name) else ""
            lines.append(f"- **{skill.name}**{active_marker}: {skill.description}")
            lines.append(f"  Location: `{skill.location}`")

        lines.append("</skills>")
        return "\n".join(lines)

    def get_skill_content(self, name: str) -> str | None:
        """
        Get the full body content of a skill.

        Args:
            name: Skill name

        Returns:
            The skill body content, or None if not found
        """
        skill = self.get_skill(name)
        if skill:
            return skill.body
        return None

    def get_triggered_skills(self) -> list[SkillMetadata]:
        """Get all skills that have at least one trigger defined."""
        return [s for s in self.get_skills() if s.triggers]


# ---------------------------------------------------------------------------
# Skill Watcher — debounced hot reload
# ---------------------------------------------------------------------------


class SkillWatcher:
    """Watch skill directories for changes and trigger re-discovery.

    Uses a simple polling approach (no external dependencies) with debounce
    to handle partial writes safely.  When a file change is detected, the
    watcher waits ``debounce_seconds`` before re-discovering skills.  This
    ensures that a SKILL.md being written incrementally (e.g., by the
    skill-creator) is fully flushed before parsing.

    Parse failures are logged as warnings and never crash the server.
    """

    def __init__(
        self,
        skill_manager: SkillManager,
        *,
        poll_interval: float = 5.0,
        debounce_seconds: float = 2.0,
        on_reload: Callable[[], Any] | None = None,
    ):
        self._mgr = skill_manager
        self._poll_interval = poll_interval
        self._debounce_seconds = debounce_seconds
        self._on_reload = on_reload  # callback after successful reload
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._snapshot: dict[str, float] = {}  # path -> mtime

    # -- lifecycle --

    async def start(self, project_root: Path | None = None) -> None:
        """Start watching skill directories."""
        self._running = True
        self._project_root = project_root
        self._snapshot = self._take_snapshot()
        self._task = asyncio.create_task(self._watch_loop())
        logger.info("SkillWatcher started (poll=%.1fs, debounce=%.1fs)", self._poll_interval, self._debounce_seconds)

    async def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("SkillWatcher stopped")

    # -- internals --

    def _get_watch_dirs(self) -> list[Path]:
        """Collect all skill directories to watch."""
        dirs = [
            self._mgr.get_builtin_skills_dir(),
            self._mgr.get_user_skills_dir(),
        ]
        if self._project_root:
            dirs.append(self._mgr.get_project_skills_dir(self._project_root))
            dirs.append(self._mgr.get_agents_skills_dir(self._project_root))
        return [d for d in dirs if d.exists()]

    def _take_snapshot(self) -> dict[str, float]:
        """Build a {path: mtime} map of all SKILL.md files."""
        snap: dict[str, float] = {}
        for d in self._get_watch_dirs():
            for skill_dir in d.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    with contextlib.suppress(OSError):
                        snap[str(skill_file)] = skill_file.stat().st_mtime
        return snap

    async def _watch_loop(self) -> None:
        """Poll for changes, debounce, then reload."""
        while self._running:
            await asyncio.sleep(self._poll_interval)
            try:
                new_snap = self._take_snapshot()
                if new_snap != self._snapshot:
                    # Something changed — debounce to let writes finish
                    logger.debug("Skill file change detected, debouncing %.1fs…", self._debounce_seconds)
                    await asyncio.sleep(self._debounce_seconds)
                    # Re-snapshot after debounce (file may have changed again)
                    new_snap = self._take_snapshot()
                    self._snapshot = new_snap
                    self._safe_reload()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("SkillWatcher poll error", exc_info=True)

    def _safe_reload(self) -> None:
        """Re-discover skills; never crash on error."""
        try:
            before = len(self._mgr.get_skills())
            self._mgr.discover_skills(self._project_root)
            after = len(self._mgr.get_skills())
            logger.info("Skills reloaded: %d → %d skills", before, after)
            if self._on_reload:
                self._on_reload()
        except Exception:
            logger.warning("Failed to reload skills (partial write?)", exc_info=True)


# Global skill manager instance
_skill_manager: SkillManager | None = None


def get_skill_manager() -> SkillManager:
    """Get or create the global skill manager."""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager


def reset_skill_manager() -> None:
    """Reset the global skill manager (for testing)."""
    global _skill_manager
    _skill_manager = None
