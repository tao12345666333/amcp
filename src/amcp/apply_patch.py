"""
Apply Patch Tool Implementation.

This module provides a diff-based file patching system inspired by OpenAI Codex's
apply_patch tool. It supports:
- Creating new files (Add File)
- Deleting files (Delete File)
- Updating files with precise hunks (Update File)
- Renaming files (Move to)

Patch Format:
    *** Begin Patch
    *** Add File: path/to/new_file.py
    +line 1
    +line 2
    *** Update File: path/to/existing.py
    @@ class ClassName
    @@ def method_name():
     context line 1
     context line 2
    -old line to remove
    +new line to add
     context line 3
    *** Delete File: path/to/obsolete.py
    *** End Patch
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PatchOperationType(Enum):
    """Types of patch operations."""

    ADD_FILE = "add"
    DELETE_FILE = "delete"
    UPDATE_FILE = "update"


class PatchError(Exception):
    """Base exception for patch errors."""

    pass


class PatchParseError(PatchError):
    """Raised when patch parsing fails."""

    pass


class PatchApplyError(PatchError):
    """Raised when patch application fails."""

    pass


@dataclass
class HunkLine:
    """A single line in a hunk."""

    prefix: str  # ' ', '-', or '+'
    text: str

    @property
    def is_context(self) -> bool:
        return self.prefix == " "

    @property
    def is_deletion(self) -> bool:
        return self.prefix == "-"

    @property
    def is_addition(self) -> bool:
        return self.prefix == "+"


@dataclass
class Hunk:
    """A hunk containing changes to apply."""

    anchors: list[str] = field(default_factory=list)  # @@ headers for context
    lines: list[HunkLine] = field(default_factory=list)

    @property
    def context_before(self) -> list[str]:
        """Get context lines before the first change."""
        result = []
        for line in self.lines:
            if line.is_context:
                result.append(line.text)
            else:
                break
        return result

    @property
    def context_after(self) -> list[str]:
        """Get context lines after the last change."""
        result: list[str] = []
        found_change = False
        for line in self.lines:
            if line.is_deletion or line.is_addition:
                found_change = True
                result = []  # Reset after each change
            elif found_change and line.is_context:
                result.append(line.text)
        return result

    @property
    def deletions(self) -> list[str]:
        """Get lines to be deleted."""
        return [line.text for line in self.lines if line.is_deletion]

    @property
    def additions(self) -> list[str]:
        """Get lines to be added."""
        return [line.text for line in self.lines if line.is_addition]


@dataclass
class FileOperation:
    """A file operation in a patch."""

    op_type: PatchOperationType
    path: str
    move_to: str | None = None  # For file renames
    content_lines: list[str] = field(default_factory=list)  # For Add File
    hunks: list[Hunk] = field(default_factory=list)  # For Update File


@dataclass
class Patch:
    """A complete patch containing multiple operations."""

    operations: list[FileOperation] = field(default_factory=list)


class PatchParser:
    """Parser for the apply_patch format."""

    # Regex patterns
    BEGIN_PATCH = re.compile(r"^\*\*\*\s*Begin\s*Patch\s*$", re.IGNORECASE)
    END_PATCH = re.compile(r"^\*\*\*\s*End\s*Patch\s*$", re.IGNORECASE)
    ADD_FILE = re.compile(r"^\*\*\*\s*Add\s*File:\s*(.+?)\s*$", re.IGNORECASE)
    DELETE_FILE = re.compile(r"^\*\*\*\s*Delete\s*File:\s*(.+?)\s*$", re.IGNORECASE)
    UPDATE_FILE = re.compile(r"^\*\*\*\s*Update\s*File:\s*(.+?)\s*$", re.IGNORECASE)
    MOVE_TO = re.compile(r"^\*\*\*\s*Move\s*to:\s*(.+?)\s*$", re.IGNORECASE)
    HUNK_HEADER = re.compile(r"^@@\s*(.*)$")
    END_OF_FILE = re.compile(r"^\*\*\*\s*End\s*of\s*File\s*$", re.IGNORECASE)

    def parse(self, patch_text: str) -> Patch:
        """Parse patch text into a Patch object."""
        lines = patch_text.split("\n")
        patch = Patch()

        i = 0
        # Find Begin Patch
        while i < len(lines):
            if self.BEGIN_PATCH.match(lines[i].strip()):
                i += 1
                break
            i += 1

        if i >= len(lines):
            raise PatchParseError("No '*** Begin Patch' found")

        # Parse operations until End Patch
        while i < len(lines):
            line = lines[i].strip()

            if self.END_PATCH.match(line):
                break

            # Try to match operation headers
            add_match = self.ADD_FILE.match(line)
            delete_match = self.DELETE_FILE.match(line)
            update_match = self.UPDATE_FILE.match(line)

            if add_match:
                op, i = self._parse_add_file(lines, i, add_match.group(1))
                patch.operations.append(op)
            elif delete_match:
                op = FileOperation(op_type=PatchOperationType.DELETE_FILE, path=delete_match.group(1))
                patch.operations.append(op)
                i += 1
            elif update_match:
                op, i = self._parse_update_file(lines, i, update_match.group(1))
                patch.operations.append(op)
            else:
                # Skip empty lines or unknown content
                i += 1

        return patch

    def _parse_add_file(self, lines: list[str], start: int, path: str) -> tuple[FileOperation, int]:
        """Parse an Add File operation."""
        op = FileOperation(op_type=PatchOperationType.ADD_FILE, path=path)
        i = start + 1

        while i < len(lines):
            line = lines[i]

            # Check for next operation or end
            if (
                self.END_PATCH.match(line.strip())
                or self.ADD_FILE.match(line.strip())
                or self.DELETE_FILE.match(line.strip())
                or self.UPDATE_FILE.match(line.strip())
            ):
                break

            # Content lines should start with +
            if line.startswith("+"):
                op.content_lines.append(line[1:])  # Remove + prefix
            i += 1

        return op, i

    def _parse_update_file(self, lines: list[str], start: int, path: str) -> tuple[FileOperation, int]:
        """Parse an Update File operation."""
        op = FileOperation(op_type=PatchOperationType.UPDATE_FILE, path=path)
        i = start + 1

        # Check for Move to
        if i < len(lines):
            move_match = self.MOVE_TO.match(lines[i].strip())
            if move_match:
                op.move_to = move_match.group(1)
                i += 1

        # Parse hunks
        current_hunk: Hunk | None = None

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Check for next operation or end
            if (
                self.END_PATCH.match(stripped)
                or self.ADD_FILE.match(stripped)
                or self.DELETE_FILE.match(stripped)
                or self.UPDATE_FILE.match(stripped)
            ):
                break

            # Check for End of File marker
            if self.END_OF_FILE.match(stripped):
                i += 1
                continue

            # Check for hunk header
            hunk_match = self.HUNK_HEADER.match(stripped)
            if hunk_match:
                if current_hunk is None:
                    current_hunk = Hunk()
                    op.hunks.append(current_hunk)
                # Add anchor (e.g., "class MyClass" or "def my_function():")
                anchor = hunk_match.group(1).strip()
                if anchor:
                    current_hunk.anchors.append(anchor)
                i += 1
                continue

            # Parse hunk lines
            if len(line) > 0 and line[0] in (" ", "-", "+"):
                if current_hunk is None:
                    current_hunk = Hunk()
                    op.hunks.append(current_hunk)

                prefix = line[0]
                text = line[1:] if len(line) > 1 else ""
                current_hunk.lines.append(HunkLine(prefix=prefix, text=text))
                i += 1
            else:
                # Skip unrecognized lines
                i += 1

        return op, i


class PatchApplier:
    """Applies parsed patches to the filesystem."""

    def __init__(self, base_dir: Path | None = None):
        """Initialize the applier.

        Args:
            base_dir: Base directory for relative paths. Defaults to cwd.
        """
        self.base_dir = base_dir or Path.cwd()
        self.applied_changes: list[dict[str, Any]] = []

    def apply(self, patch: Patch) -> list[dict[str, Any]]:
        """Apply a patch and return a summary of changes.

        Args:
            patch: The parsed patch to apply

        Returns:
            List of change summaries
        """
        self.applied_changes = []

        for op in patch.operations:
            try:
                if op.op_type == PatchOperationType.ADD_FILE:
                    self._apply_add_file(op)
                elif op.op_type == PatchOperationType.DELETE_FILE:
                    self._apply_delete_file(op)
                elif op.op_type == PatchOperationType.UPDATE_FILE:
                    self._apply_update_file(op)
            except Exception as e:
                raise PatchApplyError(f"Failed to apply {op.op_type.value} for {op.path}: {e}") from e

        return self.applied_changes

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to base_dir."""
        # Check for absolute paths first (before any cleaning)
        if path.startswith("/"):
            raise PatchApplyError(f"Absolute paths not allowed: {path}")

        # Remove any leading ./
        clean_path = path
        while clean_path.startswith("./"):
            clean_path = clean_path[2:]

        return self.base_dir / clean_path

    def _apply_add_file(self, op: FileOperation) -> None:
        """Apply an Add File operation."""
        file_path = self._resolve_path(op.path)

        # Create parent directories
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        content = "\n".join(op.content_lines)
        if op.content_lines and not content.endswith("\n"):
            content += "\n"

        file_path.write_text(content, encoding="utf-8")

        self.applied_changes.append(
            {
                "type": "add",
                "path": str(file_path),
                "lines_added": len(op.content_lines),
            }
        )
        logger.info(f"Created file: {file_path}")

    def _apply_delete_file(self, op: FileOperation) -> None:
        """Apply a Delete File operation."""
        file_path = self._resolve_path(op.path)

        if not file_path.exists():
            raise PatchApplyError(f"File not found for deletion: {file_path}")

        file_path.unlink()

        self.applied_changes.append(
            {
                "type": "delete",
                "path": str(file_path),
            }
        )
        logger.info(f"Deleted file: {file_path}")

    def _apply_update_file(self, op: FileOperation) -> None:
        """Apply an Update File operation."""
        file_path = self._resolve_path(op.path)

        if not file_path.exists():
            raise PatchApplyError(f"File not found for update: {file_path}")

        # Read current content
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        # Apply each hunk
        total_deletions = 0
        total_additions = 0

        for hunk in op.hunks:
            lines, deletions, additions = self._apply_hunk(lines, hunk, file_path)
            total_deletions += deletions
            total_additions += additions

        # Write back
        new_content = "".join(lines)

        # Handle move_to (rename)
        target_path = file_path
        if op.move_to:
            target_path = self._resolve_path(op.move_to)
            target_path.parent.mkdir(parents=True, exist_ok=True)

        target_path.write_text(new_content, encoding="utf-8")

        # Delete original if moved
        if op.move_to and file_path != target_path:
            file_path.unlink()

        self.applied_changes.append(
            {
                "type": "update",
                "path": str(file_path),
                "target_path": str(target_path) if op.move_to else None,
                "hunks_applied": len(op.hunks),
                "deletions": total_deletions,
                "additions": total_additions,
            }
        )
        logger.info(f"Updated file: {file_path}" + (f" -> {target_path}" if op.move_to else ""))

    def _apply_hunk(self, lines: list[str], hunk: Hunk, file_path: Path) -> tuple[list[str], int, int]:
        """Apply a single hunk to file lines.

        Args:
            lines: Current file lines (with newlines)
            hunk: The hunk to apply
            file_path: For error messages

        Returns:
            (updated_lines, deletions_count, additions_count)
        """
        # Build the pattern to match
        context_and_deletions = []
        for line in hunk.lines:
            if line.is_context or line.is_deletion:
                context_and_deletions.append(line.text)

        if not context_and_deletions:
            # Hunk only has additions, need to find location via anchors
            return self._apply_additions_only_hunk(lines, hunk, file_path)

        # Find the location in the file
        match_start = self._find_hunk_location(lines, hunk, context_and_deletions)

        if match_start is None:
            # Try fuzzy matching
            match_start = self._fuzzy_find_hunk_location(lines, hunk, context_and_deletions)

        if match_start is None:
            raise PatchApplyError(
                f"Could not find match for hunk in {file_path}. Looking for: {context_and_deletions[:3]}..."
            )

        # Apply the changes
        new_lines = lines[:match_start]
        i = 0
        deletions = 0
        additions = 0

        for hunk_line in hunk.lines:
            if hunk_line.is_context:
                # Keep context line
                if match_start + i < len(lines):
                    new_lines.append(lines[match_start + i])
                else:
                    new_lines.append(hunk_line.text + "\n")
                i += 1
            elif hunk_line.is_deletion:
                # Skip this line (delete it)
                i += 1
                deletions += 1
            elif hunk_line.is_addition:
                # Add new line
                text = hunk_line.text
                if not text.endswith("\n"):
                    text += "\n"
                new_lines.append(text)
                additions += 1

        # Add remaining lines
        new_lines.extend(lines[match_start + i :])

        return new_lines, deletions, additions

    def _find_hunk_location(self, lines: list[str], hunk: Hunk, pattern: list[str]) -> int | None:
        """Find where a hunk should be applied.

        Uses anchors and context to locate the exact position.
        """
        # Strip newlines for comparison
        stripped_lines = [line.rstrip("\n\r") for line in lines]
        stripped_pattern = [p.rstrip("\n\r") for p in pattern]

        if not stripped_pattern:
            return None

        # If we have anchors, find them first to narrow the search
        search_start = 0
        search_end = len(stripped_lines)

        for anchor in hunk.anchors:
            # Find anchor in file
            anchor_stripped = anchor.strip()
            for idx in range(search_start, search_end):
                if anchor_stripped in stripped_lines[idx]:
                    search_start = idx
                    break

        # Search for the pattern within the narrowed range
        pattern_len = len(stripped_pattern)

        for i in range(search_start, search_end - pattern_len + 1):
            match = True
            for j, p in enumerate(stripped_pattern):
                if stripped_lines[i + j].rstrip() != p.rstrip():
                    match = False
                    break
            if match:
                return i

        return None

    def _fuzzy_find_hunk_location(self, lines: list[str], hunk: Hunk, pattern: list[str]) -> int | None:
        """Fuzzy find hunk location by matching subset of pattern."""
        stripped_lines = [line.rstrip("\n\r") for line in lines]

        # Try matching just the first deletion or distinctive line
        for hunk_line in hunk.lines:
            if hunk_line.is_deletion:
                target = hunk_line.text.rstrip()
                for idx, line in enumerate(stripped_lines):
                    if line.rstrip() == target:
                        # Found a potential match, verify with context
                        return self._verify_and_adjust_position(stripped_lines, idx, hunk)
        return None

    def _verify_and_adjust_position(self, lines: list[str], candidate: int, hunk: Hunk) -> int | None:
        """Verify a candidate position and adjust if needed."""
        # Count context lines before first change
        context_before_count = 0
        for hunk_line in hunk.lines:
            if hunk_line.is_context:
                context_before_count += 1
            else:
                break

        # Adjust position to start of hunk
        adjusted = candidate - context_before_count
        return max(0, adjusted)

    def _apply_additions_only_hunk(self, lines: list[str], hunk: Hunk, file_path: Path) -> tuple[list[str], int, int]:
        """Handle hunks that only have additions (no context or deletions)."""
        # Use anchors to find location
        if not hunk.anchors:
            # Append to end of file
            insert_pos = len(lines)
        else:
            # Find via anchors
            insert_pos = None
            stripped_lines = [line.rstrip("\n\r") for line in lines]

            for anchor in hunk.anchors:
                anchor_stripped = anchor.strip()
                for idx, line in enumerate(stripped_lines):
                    if anchor_stripped in line:
                        insert_pos = idx + 1  # Insert after anchor
                        break
                if insert_pos is not None:
                    break

            if insert_pos is None:
                insert_pos = len(lines)

        # Insert additions
        new_lines = lines[:insert_pos]
        additions = 0

        for hunk_line in hunk.lines:
            if hunk_line.is_addition:
                text = hunk_line.text
                if not text.endswith("\n"):
                    text += "\n"
                new_lines.append(text)
                additions += 1

        new_lines.extend(lines[insert_pos:])

        return new_lines, 0, additions


def apply_patch_text(patch_text: str, base_dir: Path | None = None) -> list[dict[str, Any]]:
    """Apply a patch from text.

    Args:
        patch_text: The patch content
        base_dir: Base directory for paths

    Returns:
        List of change summaries
    """
    parser = PatchParser()
    patch = parser.parse(patch_text)
    applier = PatchApplier(base_dir)
    return applier.apply(patch)
