"""Project rules loading from AGENTS.md files.

This module implements automatic loading of project-specific rules and instructions
from AGENTS.md files, similar to OpenCode's approach. These files provide context
and instructions to guide the AI coding agent within a project.

File Locations and Precedence (highest to lowest):
1. Work directory AGENTS.md (or nested subdirectories)
2. Parent directories up to repository root
3. Global user rules: ~/.config/amcp/AGENTS.md

Supported file names:
- AGENTS.md (primary)
- AGENT.md
- .agents.md
- agents.md

Special features:
- External file references: @rules/general.md (loaded lazily)
- Override files: AGENTS.override.md (temporary overrides)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Supported file names in priority order
AGENTS_FILE_NAMES = [
    "AGENTS.md",
    "AGENT.md",
    ".agents.md",
    "agents.md",
]

# Override file names
OVERRIDE_FILE_NAMES = [
    "AGENTS.override.md",
    "AGENT.override.md",
]

# Global config directory
GLOBAL_CONFIG_DIR = Path.home() / ".config" / "amcp"


def find_git_root(start_path: Path) -> Path | None:
    """Find the git repository root from a starting path.

    Args:
        start_path: Directory to start searching from

    Returns:
        Path to git root or None if not in a git repository
    """
    current = start_path.resolve()

    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent

    return None


def find_agents_file(directory: Path) -> Path | None:
    """Find an AGENTS.md file in the given directory.

    Args:
        directory: Directory to search in

    Returns:
        Path to the agents file or None if not found
    """
    for filename in AGENTS_FILE_NAMES:
        filepath = directory / filename
        if filepath.is_file():
            return filepath
    return None


def find_override_file(directory: Path) -> Path | None:
    """Find an AGENTS.override.md file in the given directory.

    Args:
        directory: Directory to search in

    Returns:
        Path to the override file or None if not found
    """
    for filename in OVERRIDE_FILE_NAMES:
        filepath = directory / filename
        if filepath.is_file():
            return filepath
    return None


def discover_project_agents_files(work_dir: Path) -> list[Path]:
    """Discover all AGENTS.md files from work_dir up to repository root.

    Files are returned in order from repository root to work_dir,
    so more specific rules come later and can override general ones.

    Args:
        work_dir: The current working directory

    Returns:
        List of paths to AGENTS.md files, ordered from general to specific
    """
    files: list[Path] = []
    work_dir = work_dir.resolve()

    # Find git root as the boundary
    git_root = find_git_root(work_dir)
    boundary = git_root if git_root else work_dir

    # Collect directories from work_dir up to boundary (inclusive)
    directories = []
    current = work_dir
    while current >= boundary:
        directories.append(current)
        if current == boundary:
            break
        parent = current.parent
        if parent == current:  # Reached root
            break
        current = parent

    # Reverse so we go from root to work_dir (general to specific)
    directories.reverse()

    # Find AGENTS.md files in each directory
    for directory in directories:
        agents_file = find_agents_file(directory)
        if agents_file and agents_file not in files:
            files.append(agents_file)

        # Also check for override files
        override_file = find_override_file(directory)
        if override_file and override_file not in files:
            files.append(override_file)

    return files


def get_global_agents_file() -> Path | None:
    """Get the global AGENTS.md file if it exists.

    Returns:
        Path to global agents file or None
    """
    global_file = GLOBAL_CONFIG_DIR / "AGENTS.md"
    if global_file.is_file():
        return global_file
    return None


def parse_external_references(content: str) -> list[str]:
    """Parse external file references from AGENTS.md content.

    External references are in the format: @path/to/file.md
    These are meant to be loaded lazily by the agent when needed.

    Args:
        content: The AGENTS.md content

    Returns:
        List of referenced file paths
    """
    # Pattern: @path/to/file.md (at start of line or after whitespace)
    pattern = r"(?:^|\s)@([\w./\-]+\.md)"
    matches = re.findall(pattern, content)
    return matches


def load_file_content(filepath: Path) -> str | None:
    """Load content from a file.

    Args:
        filepath: Path to the file

    Returns:
        File content or None if loading fails
    """
    try:
        return filepath.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to load {filepath}: {e}")
        return None


def format_rules_section(filepath: Path, content: str) -> str:
    """Format a rules section with header indicating source.

    Args:
        filepath: Path to the rules file
        content: The file content

    Returns:
        Formatted section with header
    """
    relative_path = filepath.name
    try:
        # Try to make it relative to home or cwd
        if filepath.is_relative_to(Path.home()):
            relative_path = "~/" + str(filepath.relative_to(Path.home()))
        elif filepath.is_relative_to(Path.cwd()):
            relative_path = str(filepath.relative_to(Path.cwd()))
        else:
            relative_path = str(filepath)
    except ValueError:
        relative_path = str(filepath)

    return f"""
<!-- Project Rules: {relative_path} -->
{content.strip()}
<!-- End: {relative_path} -->
"""


class ProjectRulesLoader:
    """Loader for project-specific rules from AGENTS.md files."""

    def __init__(self, work_dir: Path | None = None):
        """Initialize the rules loader.

        Args:
            work_dir: Working directory to search from. Defaults to cwd.
        """
        self.work_dir = (work_dir or Path.cwd()).resolve()
        self._cached_rules: str | None = None
        self._loaded_files: list[Path] = []
        self._external_references: list[str] = []

    def discover_files(self) -> list[Path]:
        """Discover all relevant AGENTS.md files.

        Returns:
            List of discovered file paths
        """
        files = []

        # 1. Global rules (lowest priority)
        global_file = get_global_agents_file()
        if global_file:
            files.append(global_file)

        # 2. Project rules (higher priority, from root to work_dir)
        project_files = discover_project_agents_files(self.work_dir)
        files.extend(project_files)

        return files

    def load_rules(self) -> str:
        """Load and combine all project rules.

        Returns:
            Combined rules content ready to be added to system prompt
        """
        if self._cached_rules is not None:
            return self._cached_rules

        files = self.discover_files()
        self._loaded_files = files

        if not files:
            self._cached_rules = ""
            return ""

        sections = []
        all_references = []

        for filepath in files:
            content = load_file_content(filepath)
            if content:
                sections.append(format_rules_section(filepath, content))

                # Collect external references
                refs = parse_external_references(content)
                all_references.extend(refs)

        self._external_references = list(set(all_references))

        if not sections:
            self._cached_rules = ""
            return ""

        # Build final rules content
        rules_content = """
## Project Rules

The following project-specific rules and instructions have been loaded from AGENTS.md files.
Follow these guidelines carefully when working on this project.

""" + "\n".join(sections)

        # Add note about external references if any
        if self._external_references:
            refs_list = "\n".join(f"  - @{ref}" for ref in self._external_references)
            rules_content += f"""

### External Reference Files

The following external rule files are referenced. Load them on-demand using the read_file tool when relevant to your current task:

{refs_list}

Only load these files when they are directly relevant to avoid context crowding.
"""

        self._cached_rules = rules_content
        return rules_content

    def get_loaded_files(self) -> list[Path]:
        """Get list of loaded rule files.

        Returns:
            List of paths to files that were loaded
        """
        return self._loaded_files

    def get_external_references(self) -> list[str]:
        """Get list of external file references found in rules.

        Returns:
            List of external file paths referenced with @
        """
        return self._external_references

    def get_rules_summary(self) -> dict[str, Any]:
        """Get summary information about loaded rules.

        Returns:
            Dictionary with summary information
        """
        if self._cached_rules is None:
            self.load_rules()

        return {
            "work_dir": str(self.work_dir),
            "files_loaded": [str(f) for f in self._loaded_files],
            "file_count": len(self._loaded_files),
            "external_references": self._external_references,
            "has_rules": bool(self._cached_rules),
            "rules_length": len(self._cached_rules) if self._cached_rules else 0,
        }

    def reload(self) -> str:
        """Force reload of all rules.

        Returns:
            Newly loaded rules content
        """
        self._cached_rules = None
        self._loaded_files = []
        self._external_references = []
        return self.load_rules()


def load_project_rules(work_dir: Path | None = None) -> str:
    """Convenience function to load project rules.

    Args:
        work_dir: Working directory to search from

    Returns:
        Combined rules content
    """
    loader = ProjectRulesLoader(work_dir)
    return loader.load_rules()


def get_project_rules_info(work_dir: Path | None = None) -> dict[str, Any]:
    """Get information about project rules without loading full content.

    Args:
        work_dir: Working directory to search from

    Returns:
        Dictionary with rules information
    """
    loader = ProjectRulesLoader(work_dir)
    files = loader.discover_files()

    return {
        "work_dir": str((work_dir or Path.cwd()).resolve()),
        "discovered_files": [str(f) for f in files],
        "file_count": len(files),
        "git_root": str(find_git_root(work_dir or Path.cwd()) or "Not in git repo"),
    }
