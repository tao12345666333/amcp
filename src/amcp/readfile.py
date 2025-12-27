from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Range:
    start: int
    end: int


_DEF_BLOCK_SIZE = 5000


def _parse_range(spec: str) -> Range:
    """Parse a range specification like '1-100' or single line like '1'.

    Supports:
        - "1-100": lines 1 to 100
        - "1": just line 1 (same as "1-1")
    """
    try:
        spec = spec.strip()
        if not spec:
            raise ValueError(f"Invalid range: {spec!r}, expected 'start-end' or single line number")

        if "-" in spec:
            # Check if it's a valid range format (not just "-" or "1-" or "-10")
            parts = spec.split("-", 1)
            s, e = parts[0].strip(), parts[1].strip()

            # Handle edge cases
            if not s or not e:
                raise ValueError(f"Invalid range: {spec!r}, expected 'start-end' or single line number")

            start = int(s)
            end = int(e)
        else:
            # Single line number
            start = end = int(spec)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Invalid range: {spec!r}, expected 'start-end' or single line number") from e

    if start < 1 or end < start:
        raise ValueError(f"Invalid range: {spec!r}")
    return Range(start, end)


def read_file_with_ranges(path: Path, ranges: Iterable[str]):
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks = []
    if not ranges:
        # whole file
        r = Range(1, max(1, len(text)))
        lines = [(i + 1, text[i]) for i in range(r.start - 1, r.end)]
        blocks.append({"start": r.start, "end": r.end, "lines": lines})
        return blocks

    for spec in ranges:
        r = _parse_range(spec)
        s = max(1, r.start)
        e = min(len(text), r.end)
        if s > e:
            continue
        lines = [(i + 1, text[i]) for i in range(s - 1, e)]
        blocks.append({"start": s, "end": e, "lines": lines})
    return blocks
