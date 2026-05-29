#!/usr/bin/env python3
"""Initialize a new AMCP skill with proper directory structure.

Usage:
    python init_skill.py <skill-name> --path <output-directory> [--resources scripts,references,assets]

Examples:
    python init_skill.py my-skill --path .amcp/skills
    python init_skill.py my-skill --path ~/.config/amcp/skills --resources scripts,references
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
MAX_NAME_LENGTH = 64

SKILL_MD_TEMPLATE = """---
name: {name}
description: TODO - Describe what this skill does and when to use it. Be specific about triggers and use cases.
auto_trigger: true
---

# {title}

TODO - Write instructions for using this skill.

## Overview

Describe the skill's purpose and capabilities.

## Usage

Provide step-by-step instructions.

## Examples

Include concrete examples of how to use this skill.
"""


def validate_name(name: str) -> str | None:
    """Validate skill name, return error message or None."""
    if len(name) > MAX_NAME_LENGTH:
        return f"Name too long: {len(name)} chars (max {MAX_NAME_LENGTH})"
    if not VALID_NAME_RE.match(name):
        return f"Invalid name '{name}'. Use lowercase letters, digits, and hyphens only."
    if "--" in name:
        return f"Invalid name '{name}'. Consecutive hyphens not allowed."
    return None


def create_skill(name: str, output_dir: Path, resources: list[str] | None = None) -> Path:
    """Create a new skill directory with template files.

    Args:
        name: Skill name (lowercase, hyphens)
        output_dir: Parent directory for the skill
        resources: Optional list of resource dirs to create (scripts, references, assets)

    Returns:
        Path to the created skill directory
    """
    # Validate name
    error = validate_name(name)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    # Resolve output directory
    skill_dir = output_dir.expanduser().resolve() / name
    if skill_dir.exists():
        print(f"Error: Directory already exists: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    # Create skill directory
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Generate title from name
    title = name.replace("-", " ").title()

    # Write SKILL.md
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        SKILL_MD_TEMPLATE.format(name=name, title=title),
        encoding="utf-8",
    )
    print(f"Created: {skill_md}")

    # Create resource directories
    if resources:
        for resource in resources:
            resource = resource.strip().lower()
            if resource in ("scripts", "references", "assets"):
                resource_dir = skill_dir / resource
                resource_dir.mkdir(exist_ok=True)
                # Add a .gitkeep to track empty dirs
                (resource_dir / ".gitkeep").touch()
                print(f"Created: {resource_dir}/")
            else:
                print(f"Warning: Unknown resource type '{resource}', skipping.", file=sys.stderr)

    print(f"\nSkill '{name}' initialized at: {skill_dir}")
    print("Next steps:")
    print(f"  1. Edit {skill_md} - update description and body")
    if resources:
        print("  2. Add scripts, references, or assets as needed")
    print(f"  3. Validate: python validate_skill.py {skill_dir}")
    return skill_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize a new AMCP skill")
    parser.add_argument("name", help="Skill name (lowercase, hyphens, digits)")
    parser.add_argument("--path", required=True, help="Output directory for the skill")
    parser.add_argument(
        "--resources",
        help="Comma-separated resource directories to create (scripts,references,assets)",
        default=None,
    )
    args = parser.parse_args()

    resources = args.resources.split(",") if args.resources else None
    create_skill(args.name, Path(args.path), resources)


if __name__ == "__main__":
    main()
