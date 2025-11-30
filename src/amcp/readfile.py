from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Range:
    start: int
    end: int


_DEF_BLOCK_SIZE = 5000


def _parse_range(spec: str) -> Range:
    try:
        s, e = spec.split("-", 1)
        start = int(s)
        end = int(e)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid range: {spec!r}, expected start-end") from e
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
