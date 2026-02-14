from __future__ import annotations

import re
from dataclasses import dataclass

_MARKDOWN_V2_SPECIALS = r"_*[]()~`>#+-=|{}.!"
_MARKDOWN_ESCAPE_RE = re.compile(rf"([{re.escape(_MARKDOWN_V2_SPECIALS)}])")


@dataclass
class Segment:
    kind: str
    content: str
    language: str | None = None


class TelegramFormatter:
    """Convert agent output to Telegram MarkdownV2 format."""

    def __init__(self, max_length: int = 4096) -> None:
        self.max_length = max_length

    def format_response(self, text: str) -> list[str]:
        segments = self._split_segments(text)
        chunks: list[str] = []
        current = ""

        for segment in segments:
            if segment.kind == "code":
                parts = self._format_code_segment(segment.content, segment.language)
            else:
                formatted_text = self._format_text(segment.content)
                parts = self._split_text(formatted_text)

            for part in parts:
                if not part:
                    continue
                if len(part) > self.max_length:
                    for sub in self._split_text(part):
                        current, chunks = self._append_chunk(current, sub, chunks)
                    continue
                current, chunks = self._append_chunk(current, part, chunks)

        if current:
            chunks.append(current)
        return chunks

    def format_error(self, error: str) -> str:
        return f"Error: {self._escape_markdown(error)}"

    def format_tool_call(self, tool_name: str, result: str) -> str:
        safe_name = self._escape_markdown(tool_name)
        safe_result = self._escape_markdown(result[:500])
        return f"Tool `{safe_name}`\n{safe_result}"

    def _append_chunk(self, current: str, part: str, chunks: list[str]) -> tuple[str, list[str]]:
        if not current:
            return part, chunks
        if len(current) + len(part) > self.max_length:
            chunks.append(current)
            return part, chunks
        return current + part, chunks

    def _split_segments(self, text: str) -> list[Segment]:
        segments: list[Segment] = []
        lines = text.splitlines(keepends=True)
        buffer: list[str] = []
        in_code = False
        language: str | None = None

        for line in lines:
            if line.startswith("```"):
                if in_code:
                    segments.append(Segment("code", "".join(buffer), language))
                    buffer = []
                    in_code = False
                    language = None
                else:
                    if buffer:
                        segments.append(Segment("text", "".join(buffer)))
                    buffer = []
                    in_code = True
                    language = line[3:].strip() or None
                continue
            buffer.append(line)

        if buffer:
            kind = "code" if in_code else "text"
            segments.append(Segment(kind, "".join(buffer), language))

        return segments

    def _format_text(self, text: str) -> str:
        parts: list[str] = []
        in_code = False
        buffer: list[str] = []

        for char in text:
            if char == "`":
                if in_code:
                    code = "".join(buffer)
                    parts.append(f"`{self._escape_code(code)}`")
                    buffer = []
                    in_code = False
                else:
                    if buffer:
                        parts.append(self._escape_markdown("".join(buffer)))
                        buffer = []
                    in_code = True
            else:
                buffer.append(char)

        if buffer:
            if in_code:
                parts.append(self._escape_markdown("`" + "".join(buffer)))
            else:
                parts.append(self._escape_markdown("".join(buffer)))

        return "".join(parts)

    def _format_code_segment(self, code: str, language: str | None) -> list[str]:
        escaped = self._escape_code(code)
        if not escaped.endswith("\n"):
            escaped += "\n"
        header = f"```{language}\n" if language else "```\n"
        footer = "```"
        max_payload = self.max_length - len(header) - len(footer)
        if max_payload < 1:
            max_payload = 1

        parts: list[str] = []
        buffer = ""

        for line in escaped.splitlines(keepends=True):
            if len(buffer) + len(line) > max_payload and buffer:
                parts.append(self._wrap_code(header, buffer, footer))
                buffer = ""
            if len(line) > max_payload:
                parts.append(self._wrap_code(header, line[:max_payload], footer))
                remainder = line[max_payload:]
                while remainder:
                    parts.append(self._wrap_code(header, remainder[:max_payload], footer))
                    remainder = remainder[max_payload:]
                continue
            buffer += line

        if buffer:
            parts.append(self._wrap_code(header, buffer, footer))

        return parts

    def _wrap_code(self, header: str, payload: str, footer: str) -> str:
        payload = payload.rstrip("\n") + "\n"
        return f"{header}{payload}{footer}"

    def _split_text(self, text: str) -> list[str]:
        if len(text) <= self.max_length:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= self.max_length:
                chunks.append(remaining)
                break
            cut = remaining.rfind("\n", 0, self.max_length)
            if cut == -1:
                cut = remaining.rfind(" ", 0, self.max_length)
            if cut <= 0:
                cut = self.max_length
            chunk = remaining[:cut].rstrip()
            chunks.append(chunk)
            remaining = remaining[cut:].lstrip()

        return chunks

    def _escape_markdown(self, text: str) -> str:
        return _MARKDOWN_ESCAPE_RE.sub(r"\\\1", text)

    def _escape_code(self, text: str) -> str:
        return text.replace("\\", "\\\\").replace("`", "\\`")
