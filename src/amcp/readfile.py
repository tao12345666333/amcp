"""File reading utilities with range and indentation-aware modes.

Inspired by OpenAI Codex's read_file tool, this module supports:
- Simple line ranges (slice mode)
- Indentation-aware block reading (indentation mode)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Constants
TAB_WIDTH = 4
MAX_LINE_LENGTH = 500
COMMENT_PREFIXES = ("#", "//", "--", "/*", "'''", '"""')


@dataclass
class Range:
    start: int
    end: int


@dataclass
class LineRecord:
    """A line with metadata for indentation processing."""

    number: int
    raw: str
    display: str
    indent: int

    @property
    def trimmed(self) -> str:
        return self.raw.lstrip()

    @property
    def is_blank(self) -> bool:
        return not self.trimmed

    @property
    def is_comment(self) -> bool:
        return any(self.raw.strip().startswith(p) for p in COMMENT_PREFIXES)


@dataclass
class IndentationOptions:
    """Options for indentation-aware reading."""

    anchor_line: int | None = None
    max_levels: int = 0  # 0 = unlimited
    include_siblings: bool = False
    include_header: bool = True
    max_lines: int | None = None


def _parse_range(spec: str) -> Range:
    """Parse a range specification like '1-100' or single line like '1'.

    Supports:
        - "1-100": lines 1 to 100
        - "1": just line 1 (same as "1-1")
        - "0" or negative: auto-corrected to 1
        - Invalid inputs like "-" or "" are auto-corrected to Range(1, 1)
    """
    try:
        spec = spec.strip()
        # Handle empty or just-hyphen inputs gracefully (LLM resilience)
        if not spec or spec == "-":
            return Range(1, 1)  # Default to first line instead of raising

        # First, try to parse as a single integer (handles negative numbers like "-5")
        try:
            start = end = int(spec)
        except ValueError:
            # Not a single integer, try parsing as range format "start-end"
            if "-" in spec:
                # Find the last hyphen (to handle cases like "1-100", not "-5")
                # We need to distinguish between "-5" (negative number) and "1-5" (range)
                parts = spec.rsplit("-", 1)
                if len(parts) == 2 and parts[0] and parts[1]:
                    s, e = parts[0].strip(), parts[1].strip()
                    start = int(s)
                    end = int(e)
                else:
                    raise ValueError(f"Invalid range: {spec!r}, expected 'start-end' or single line number") from None
            else:
                raise ValueError(f"Invalid range: {spec!r}, expected 'start-end' or single line number") from None
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Invalid range: {spec!r}, expected 'start-end' or single line number") from e

    # Auto-correct invalid start line (0 or negative) to 1
    # This makes the tool more resilient to LLM mistakes (0-indexed vs 1-indexed confusion)
    if start < 1:
        start = 1
    if end < start:
        end = start
    return Range(start, end)


def _measure_indent(line: str) -> int:
    """Measure indentation level in spaces (tabs = TAB_WIDTH spaces)."""
    indent = 0
    for char in line:
        if char == " ":
            indent += 1
        elif char == "\t":
            indent += TAB_WIDTH
        else:
            break
    return indent


def _truncate_line(line: str, max_length: int = MAX_LINE_LENGTH) -> str:
    """Truncate line if too long."""
    if len(line) > max_length:
        return line[:max_length] + "..."
    return line


def _collect_file_lines(text: list[str]) -> list[LineRecord]:
    """Convert file lines to LineRecords with metadata."""
    records = []
    for i, raw in enumerate(text):
        display = _truncate_line(raw)
        indent = _measure_indent(raw)
        records.append(LineRecord(number=i + 1, raw=raw, display=display, indent=indent))
    return records


def _compute_effective_indents(records: list[LineRecord]) -> list[int]:
    """Compute effective indentation for each line.

    Blank lines inherit the previous non-blank line's indent.
    """
    effective = []
    previous_indent = 0
    for record in records:
        if record.is_blank:
            effective.append(previous_indent)
        else:
            previous_indent = record.indent
            effective.append(previous_indent)
    return effective


def read_file_with_ranges(path: Path, ranges: Iterable[str]) -> list[dict]:
    """Read file with specified line ranges (slice mode)."""
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks = []

    if not ranges:
        # whole file
        r = Range(1, max(1, len(text)))
        lines = [(i + 1, _truncate_line(text[i])) for i in range(r.start - 1, r.end)]
        blocks.append({"start": r.start, "end": r.end, "lines": lines})
        return blocks

    for spec in ranges:
        r = _parse_range(spec)
        s = max(1, r.start)
        e = min(len(text), r.end)
        if s > e:
            continue
        lines = [(i + 1, _truncate_line(text[i])) for i in range(s - 1, e)]
        blocks.append({"start": s, "end": e, "lines": lines})
    return blocks


def read_file_with_indentation(
    path: Path,
    offset: int,
    limit: int,
    options: IndentationOptions | None = None,
) -> list[dict]:
    """Read file using indentation-aware block mode.

    This mode intelligently expands around an anchor line based on indentation,
    capturing the complete code block context (function, class, etc.).

    Args:
        path: Path to the file
        offset: Starting line number (1-indexed)
        limit: Maximum lines to return
        options: Indentation-specific options

    Returns:
        List of blocks with lines and metadata
    """
    options = options or IndentationOptions()
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()

    if not text:
        return [{"start": 0, "end": 0, "lines": [], "mode": "indentation"}]

    anchor_line = options.anchor_line or offset
    if anchor_line < 1 or anchor_line > len(text):
        raise ValueError(f"anchor_line {anchor_line} is out of range (1-{len(text)})")

    records = _collect_file_lines(text)
    effective_indents = _compute_effective_indents(records)

    anchor_index = anchor_line - 1
    anchor_indent = effective_indents[anchor_index]

    # Calculate minimum indent to include
    min_indent = 0 if options.max_levels == 0 else max(0, anchor_indent - options.max_levels * TAB_WIDTH)

    # Cap limit by options.max_lines
    guard_limit = options.max_lines or limit
    final_limit = min(limit, guard_limit, len(records))

    if final_limit == 1:
        return [
            {
                "start": anchor_line,
                "end": anchor_line,
                "lines": [(anchor_line, records[anchor_index].display)],
                "mode": "indentation",
                "anchor": anchor_line,
            }
        ]

    # Expand from anchor in both directions
    result: list[LineRecord] = [records[anchor_index]]
    i = anchor_index - 1  # up
    j = anchor_index + 1  # down
    i_min_count = 0
    j_min_count = 0

    while len(result) < final_limit:
        progressed = False

        # Expand upward
        if i >= 0:
            if effective_indents[i] >= min_indent:
                result.insert(0, records[i])
                progressed = True

                # Stop at min_indent boundary unless it's a comment header
                if effective_indents[i] == min_indent and not options.include_siblings:
                    allow_header = options.include_header and records[i].is_comment
                    if i_min_count == 0 or allow_header:
                        i_min_count += 1
                    else:
                        # Remove this line, shouldn't have been added
                        result.pop(0)
                        progressed = False
                        i = -1  # Stop going up

                i -= 1

                if len(result) >= final_limit:
                    break
            else:
                i = -1  # Stop going up

        # Expand downward
        if j < len(records):
            if effective_indents[j] >= min_indent:
                result.append(records[j])
                progressed = True

                # Stop at min_indent boundary unless including siblings
                if effective_indents[j] == min_indent and not options.include_siblings:
                    if j_min_count > 0:
                        result.pop()
                        progressed = False
                        j = len(records)  # Stop going down
                    j_min_count += 1

                j += 1
            else:
                j = len(records)  # Stop going down

        if not progressed:
            break

    # Trim blank lines from edges
    while result and result[0].is_blank:
        result.pop(0)
    while result and result[-1].is_blank:
        result.pop()

    if not result:
        return [{"start": 0, "end": 0, "lines": [], "mode": "indentation"}]

    lines = [(r.number, r.display) for r in result]
    return [
        {
            "start": result[0].number,
            "end": result[-1].number,
            "lines": lines,
            "mode": "indentation",
            "anchor": anchor_line,
        }
    ]
