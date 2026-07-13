from __future__ import annotations

import re

from telegramify_markdown import convert, split_markdownv2

_MARKDOWN_V2_SPECIALS = r"_*[]()~`>#+-=|{}.!"
_MARKDOWN_ESCAPE_RE = re.compile(rf"([{re.escape(_MARKDOWN_V2_SPECIALS)}])")


class TelegramFormatter:
    """Convert agent output to Telegram MarkdownV2 format."""

    def __init__(self, max_length: int = 4096) -> None:
        self.max_length = max_length

    def format_response(self, text: str) -> list[str]:
        """Convert standard Markdown and split it into valid Telegram messages."""
        plain_text, entities = convert(text)
        return split_markdownv2(plain_text, entities, max_utf16_len=self.max_length)

    def format_error(self, error: str) -> str:
        return f"Error: {self._escape_markdown(error)}"

    def format_tool_call(self, tool_name: str, result: str) -> str:
        safe_name = self._escape_markdown(tool_name)
        safe_result = self._escape_markdown(result[:500])
        return f"Tool `{safe_name}`\n{safe_result}"

    def _escape_markdown(self, text: str) -> str:
        return _MARKDOWN_ESCAPE_RE.sub(r"\\\1", text)
