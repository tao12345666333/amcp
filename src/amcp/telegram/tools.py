"""Telegram tools for AMCP agents.

Provides a first-class TelegramSendTool that allows agents to send and edit
Telegram messages directly through the Bot API, replacing the subprocess-based
telegram-sender skill script.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..config import load_config
from ..tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramSendTool(BaseTool):
    """Tool for sending and editing Telegram messages via the Bot API.

    Uses synchronous HTTP requests to the Telegram Bot API, avoiding
    async bridging issues when called from the synchronous tool execute path.
    """

    def __init__(self, bot_token: str | None = None) -> None:
        super().__init__()
        self._bot_token = bot_token or os.environ.get("AMCP_TELEGRAM_BOT_TOKEN", "")

    @property
    def name(self) -> str:
        return "telegram_send"

    @property
    def description(self) -> str:
        return """Send, edit, or broadcast messages via Telegram Bot API.

Actions:
- send: Send a new message to a chat
- edit: Edit an existing message
- notify: Send a message to all allowed users (broadcast)

Examples:
  Send: {"action": "send", "chat_id": "123456", "text": "Hello!"}
  Edit: {"action": "edit", "chat_id": "123456", "message_id": 42, "text": "Updated"}
  Reply: {"action": "send", "chat_id": "123456", "text": "Reply", "reply_to_message_id": 42}
  Notify: {"action": "notify", "text": "Deployment complete"}

The text supports Markdown formatting which is auto-converted to MarkdownV2."""

    def execute(  # type: ignore[override]
        self,
        action: str,
        text: str,
        chat_id: str | int | None = None,
        message_id: int | None = None,
        reply_to_message_id: int | None = None,
    ) -> ToolResult:
        """Execute a Telegram messaging action.

        Args:
            action: One of "send", "edit", "notify".
            text: Message content (Markdown supported).
            chat_id: Target chat ID (required for send/edit).
            message_id: Message ID to edit (required for edit).
            reply_to_message_id: Optional message ID to reply to (for send).
        """
        if not self._bot_token:
            return ToolResult(
                success=False,
                content="",
                error="Telegram bot token not configured. "
                "Set AMCP_TELEGRAM_BOT_TOKEN or pass bot_token.",
            )

        if action == "send":
            return self._send(text, chat_id, reply_to_message_id)
        elif action == "edit":
            return self._edit(text, chat_id, message_id)
        elif action == "notify":
            return self._notify(text)
        else:
            return ToolResult(
                success=False,
                content="",
                error=f"Invalid action '{action}'. Use: send, edit, notify",
            )

    def _convert_markdown(self, text: str) -> str:
        """Convert markdown text to MarkdownV2 format."""
        try:
            from telegramify_markdown import markdownify

            return markdownify(text).rstrip("\n")
        except ImportError:
            logger.debug("telegramify_markdown not available, sending as plain text")
            return text

    def _get_parse_mode(self) -> str | None:
        """Return parse mode based on availability of markdown converter."""
        try:
            from telegramify_markdown import markdownify  # noqa: F401

            return "MarkdownV2"
        except ImportError:
            return None

    def _api_url(self, method: str) -> str:
        return f"{TELEGRAM_API_BASE}/bot{self._bot_token}/{method}"

    def _post(self, method: str, payload: dict[str, Any]) -> ToolResult:
        """Make a POST request to the Telegram Bot API."""
        url = self._api_url(method)
        try:
            response = httpx.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            result_data = data.get("result", {})
            msg_id = result_data.get("message_id", "")
            return ToolResult(
                success=True,
                content=f"OK (message_id={msg_id})",
                metadata={"message_id": msg_id, "method": method},
            )
        except httpx.HTTPStatusError as e:
            body = e.response.text if e.response is not None else ""
            return ToolResult(
                success=False,
                content="",
                error=f"Telegram API error {e.response.status_code}: {body}",
            )
        except httpx.HTTPError as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Telegram API request failed: {e}",
            )

    def _send(
        self,
        text: str,
        chat_id: str | int | None,
        reply_to_message_id: int | None,
    ) -> ToolResult:
        """Send a new message."""
        if not chat_id:
            return ToolResult(
                success=False,
                content="",
                error="chat_id is required for send action.",
            )

        converted = self._convert_markdown(text)
        parse_mode = self._get_parse_mode()

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": converted,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        return self._post("sendMessage", payload)

    def _edit(
        self,
        text: str,
        chat_id: str | int | None,
        message_id: int | None,
    ) -> ToolResult:
        """Edit an existing message."""
        if not chat_id:
            return ToolResult(
                success=False,
                content="",
                error="chat_id is required for edit action.",
            )
        if not message_id:
            return ToolResult(
                success=False,
                content="",
                error="message_id is required for edit action.",
            )

        converted = self._convert_markdown(text)
        parse_mode = self._get_parse_mode()

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": converted,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        return self._post("editMessageText", payload)

    def _notify(self, text: str) -> ToolResult:
        """Send a notification to all allowed users."""
        cfg = load_config()
        if not cfg.telegram or not cfg.telegram.allowed_users:
            return ToolResult(
                success=False,
                content="",
                error="No allowed users configured for notifications.",
            )

        results = []
        errors = []
        for user_id in cfg.telegram.allowed_users:
            result = self._send(text, str(user_id), reply_to_message_id=None)
            if result.success:
                results.append(user_id)
            else:
                errors.append(f"user {user_id}: {result.error}")

        if errors:
            return ToolResult(
                success=len(results) > 0,
                content=f"Sent to {len(results)} user(s), {len(errors)} failed.",
                error="; ".join(errors) if not results else None,
                metadata={"sent_to": results, "errors": errors},
            )

        return ToolResult(
            success=True,
            content=f"Notification sent to {len(results)} user(s).",
            metadata={"sent_to": results},
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["send", "edit", "notify"],
                    "description": "Action to perform",
                },
                "text": {
                    "type": "string",
                    "description": "Message content (Markdown supported)",
                },
                "chat_id": {
                    "type": "string",
                    "description": "Target chat ID (required for send/edit)",
                },
                "message_id": {
                    "type": "integer",
                    "description": "Message ID to edit (required for edit action)",
                },
                "reply_to_message_id": {
                    "type": "integer",
                    "description": "Message ID to reply to (optional, for send action)",
                },
            },
            "required": ["action", "text"],
            "additionalProperties": False,
        }
