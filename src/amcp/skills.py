"""
Skills system for AMCP.

Skills are reusable knowledge or behavior definitions that can be activated
to provide specialized capabilities to the agent. They are defined as
markdown files with YAML frontmatter containing:
- name: The skill name
- description: A brief description of what the skill provides

Skills are discovered from:
- User skills: ~/.config/amcp/skills/<skill-name>/SKILL.md
- Project skills: .amcp/skills/<skill-name>/SKILL.md (takes precedence)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

if TYPE_CHECKING:
    pass

# Regex to parse YAML frontmatter
FRONTMATTER_REGEX = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)", re.MULTILINE)

# Default config directory
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "amcp"


@dataclass
class SkillMetadata:
    """Metadata for a discovered skill."""

    name: str
    description: str
    location: str
    body: str
    disabled: bool = False


@dataclass
class SkillManager:
    """
    Manages the discovery and lifecycle of skills.

    Skills can be discovered from user-level and project-level directories.
    Project skills take precedence over user skills with the same name.
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

    def clear_skills(self) -> None:
        """Clear all discovered skills."""
        self._skills = []

    def discover_skills(self, project_root: Path | None = None) -> None:
        """
        Discover skills from standard user and project locations.

        Project skills take precedence over user skills with the same name.

        Args:
            project_root: The project root directory (defaults to cwd)
        """
        self.clear_skills()

        # Discover user skills first
        user_skills_dir = self.get_user_skills_dir()
        user_skills = self._discover_skills_from_dir(user_skills_dir)
        self._add_skills_with_precedence(user_skills)

        # Discover project skills (takes precedence)
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

            return SkillMetadata(
                name=name,
                description=description if isinstance(description, str) else "",
                location=str(file_path),
                body=body,
                disabled=name in self._disabled_skill_names,
            )
        except Exception:
            return None

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
