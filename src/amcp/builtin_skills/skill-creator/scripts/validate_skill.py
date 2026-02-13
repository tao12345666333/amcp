#!/usr/bin/env python3
"""Validate an AMCP skill directory.

Checks:
- SKILL.md exists
- YAML frontmatter is valid
- Required fields (name, description) are present
- Naming conventions are followed
- Description is not a placeholder
- File organization is correct

Usage:
    python validate_skill.py <path/to/skill-folder>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
FRONTMATTER_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)", re.MULTILINE)
MAX_NAME_LENGTH = 64
MAX_SKILL_LINES = 500


def parse_simple_yaml(text: str) -> dict[str, str]:
    """Parse simple YAML key-value pairs."""
    result = {}
    for line in text.strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            result[key] = value
    return result


def validate_skill(skill_dir: Path) -> list[str]:
    """Validate a skill directory.

    Args:
        skill_dir: Path to the skill directory

    Returns:
        List of error messages (empty = valid)
    """
    errors: list[str] = []

    # Check directory exists
    if not skill_dir.is_dir():
        errors.append(f"Not a directory: {skill_dir}")
        return errors

    # Check SKILL.md exists
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        errors.append(f"Missing SKILL.md in {skill_dir}")
        return errors

    # Read content
    try:
        content = skill_md.read_text(encoding="utf-8")
    except Exception as e:
        errors.append(f"Cannot read SKILL.md: {e}")
        return errors

    # Check frontmatter
    match = FRONTMATTER_RE.match(content)
    if not match:
        errors.append("Missing or invalid YAML frontmatter (must start with ---)")
        return errors

    frontmatter_text = match.group(1)
    body = match.group(2).strip()

    # Parse frontmatter
    metadata = parse_simple_yaml(frontmatter_text)

    # Check required fields
    if "name" not in metadata or not metadata["name"]:
        errors.append("Missing required field: name")

    if "description" not in metadata or not metadata["description"]:
        errors.append("Missing required field: description")

    # Validate name
    name = metadata.get("name", "")
    if name:
        if len(name) > MAX_NAME_LENGTH:
            errors.append(f"Name too long: {len(name)} chars (max {MAX_NAME_LENGTH})")
        if not VALID_NAME_RE.match(name):
            errors.append(f"Invalid name '{name}'. Use lowercase letters, digits, and hyphens only.")
        if "--" in name:
            errors.append(f"Name contains consecutive hyphens: '{name}'")

        # Check name matches directory
        if skill_dir.name != name:
            errors.append(f"Directory name '{skill_dir.name}' does not match skill name '{name}'")

    # Check description quality
    desc = metadata.get("description", "")
    if desc:
        if desc.startswith("TODO"):
            errors.append("Description is still a placeholder (starts with TODO)")
        if len(desc) < 20:
            errors.append(
                f"Description too short ({len(desc)} chars). Be specific about what the skill does and when to use it."
            )

    # Check body
    if not body:
        errors.append("SKILL.md body is empty")

    # Check body length
    body_lines = body.split("\n")
    if len(body_lines) > MAX_SKILL_LINES:
        errors.append(
            f"SKILL.md body too long ({len(body_lines)} lines, max {MAX_SKILL_LINES}). Consider splitting into reference files."
        )

    # Check for extraneous files
    forbidden_files = {"README.md", "CHANGELOG.md", "INSTALLATION_GUIDE.md", "QUICK_REFERENCE.md"}
    for item in skill_dir.iterdir():
        if item.name in forbidden_files:
            errors.append(
                f"Extraneous file: {item.name} (skills should only contain SKILL.md and resource directories)"
            )

    return errors


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python validate_skill.py <path/to/skill-folder>", file=sys.stderr)
        sys.exit(1)

    skill_dir = Path(sys.argv[1]).resolve()
    errors = validate_skill(skill_dir)

    if errors:
        print(f"❌ Validation failed for: {skill_dir}")
        for error in errors:
            print(f"  • {error}")
        sys.exit(1)
    else:
        print(f"✅ Skill is valid: {skill_dir}")


if __name__ == "__main__":
    main()
