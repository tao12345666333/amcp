from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..memory import get_memory_manager
from ..skills import get_skill_manager
from .auth import AuthMiddleware

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

    from .bot import TelegramBot


@dataclass
class TelegramSession:
    session_id: str
    agent: Any
    last_used: datetime = field(default_factory=datetime.now)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    queue: deque[TelegramQueuedMessage] = field(default_factory=deque)
    current_task: asyncio.Task | None = None


@dataclass
class TelegramQueuedMessage:
    chat_id: int
    user_id: int
    text: str = ""
    message_type: str = "text"
    metadata: dict[str, Any] | None = None


def _format_photo_message(message: Any) -> tuple[str, dict[str, Any] | None]:
    caption = _parse_caption(message)
    photos = getattr(message, "photo", None) or []
    if not photos:
        formatted = "[Photo message]" + (f" Caption: {caption}" if caption else "")
        return formatted, None
    largest = photos[-1]
    result = {"file_id": largest.file_id}
    if largest.file_size:
        result["file_size"] = largest.file_size
    if largest.width:
        result["width"] = largest.width
    if largest.height:
        result["height"] = largest.height
    formatted = "[Photo message]" + (f" Caption: {caption}" if caption else "")
    return formatted, result


def _format_audio_message(message: Any) -> tuple[str, dict[str, Any] | None]:
    audio = getattr(message, "audio", None)
    if audio is None:
        return "[Audio]", None
    duration = audio.duration or 0
    title = audio.title or "Unknown"
    performer = audio.performer or ""
    result = {"file_id": audio.file_id}
    if audio.file_size:
        result["file_size"] = audio.file_size
    if audio.duration:
        result["duration"] = audio.duration
    if audio.title:
        result["title"] = audio.title
    if audio.performer:
        result["performer"] = audio.performer
    formatted = f"[Audio: {performer} - {title} ({duration}s)]" if performer else f"[Audio: {title} ({duration}s)]"
    return formatted, result


def _format_video_message(message: Any) -> tuple[str, dict[str, Any] | None]:
    video = getattr(message, "video", None)
    caption = _parse_caption(message)
    if video is None:
        formatted = "[Video]" + (f" Caption: {caption}" if caption else "")
        return formatted, None
    duration = video.duration or 0
    result: dict[str, Any] = {"file_id": video.file_id}
    if video.file_size:
        result["file_size"] = video.file_size
    if video.width:
        result["width"] = video.width
    if video.height:
        result["height"] = video.height
    if video.duration:
        result["duration"] = video.duration
    formatted = f"[Video: {duration}s]" + (f" Caption: {caption}" if caption else "")
    return formatted, result


def _format_document_message(message: Any) -> tuple[str, dict[str, Any] | None]:
    document = getattr(message, "document", None)
    caption = _parse_caption(message)
    if document is None:
        formatted = "[Document]" + (f" Caption: {caption}" if caption else "")
        return formatted, None
    file_name = document.file_name or "unknown"
    mime_type = document.mime_type or "unknown"
    result = {"file_id": document.file_id, "file_name": document.file_name, "mime_type": document.mime_type}
    if document.file_size:
        result["file_size"] = document.file_size
    formatted = f"[Document: {file_name} ({mime_type})]" + (f" Caption: {caption}" if caption else "")
    return formatted, result


def _format_voice_message(message: Any) -> tuple[str, dict[str, Any] | None]:
    voice = getattr(message, "voice", None)
    if voice is None:
        return "[Voice]", None
    duration = voice.duration or 0
    result = {"file_id": voice.file_id}
    if voice.duration:
        result["duration"] = voice.duration
    return f"[Voice message: {duration}s]", result


def _format_video_note_message(message: Any) -> tuple[str, dict[str, Any] | None]:
    video_note = getattr(message, "video_note", None)
    if video_note is None:
        return "[Video note]", None
    duration = video_note.duration or 0
    result = {"file_id": video_note.file_id}
    if video_note.duration:
        result["duration"] = video_note.duration
    return f"[Video note: {duration}s]", result


def _format_sticker_message(message: Any) -> tuple[str, dict[str, Any] | None]:
    sticker = getattr(message, "sticker", None)
    if sticker is None:
        return "[Sticker]", None
    emoji = sticker.emoji or ""
    set_name = sticker.set_name or ""
    result = {"file_id": sticker.file_id}
    if sticker.width:
        result["width"] = sticker.width
    if sticker.height:
        result["height"] = sticker.height
    if sticker.emoji:
        result["emoji"] = sticker.emoji
    if sticker.set_name:
        result["set_name"] = sticker.set_name
    formatted = f"[Sticker: {emoji}]" if emoji else "[Sticker]"
    if set_name:
        formatted += f" from {set_name}"
    return formatted, result


def _message_type(message: Any) -> str:
    if getattr(message, "text", None):
        return "text"
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "audio", None):
        return "audio"
    if getattr(message, "sticker", None):
        return "sticker"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "voice", None):
        return "voice"
    if getattr(message, "document", None):
        return "document"
    if getattr(message, "video_note", None):
        return "video_note"
    return "unknown"


def _parse_caption(message: Any) -> str:
    return getattr(message, "caption", None) or ""


def _parse_message(message: Any) -> tuple[str, str, dict[str, Any] | None]:
    """Parse message and return (text, message_type, metadata)."""
    msg_type = _message_type(message)
    if msg_type == "text":
        return getattr(message, "text", None) or "", msg_type, None
    if msg_type == "photo":
        text, metadata = _format_photo_message(message)
        return text, msg_type, metadata
    if msg_type == "audio":
        text, metadata = _format_audio_message(message)
        return text, msg_type, metadata
    if msg_type == "video":
        text, metadata = _format_video_message(message)
        return text, msg_type, metadata
    if msg_type == "document":
        text, metadata = _format_document_message(message)
        return text, msg_type, metadata
    if msg_type == "voice":
        text, metadata = _format_voice_message(message)
        return text, msg_type, metadata
    if msg_type == "video_note":
        text, metadata = _format_video_note_message(message)
        return text, msg_type, metadata
    if msg_type == "sticker":
        text, metadata = _format_sticker_message(message)
        return text, msg_type, metadata
    return "[Unknown message type]", "unknown", None


_MEDIA_PARSERS: dict[str, Any] = {}


def _exclude_none(d: dict[str, Any]) -> dict[str, Any]:
    """Remove None values from a dict."""
    return {k: v for k, v in d.items() if v is not None}


def _extract_reply_metadata(message: Any) -> dict[str, Any] | None:
    """Extract metadata from a reply_to_message."""
    reply_to = getattr(message, "reply_to_message", None)
    if reply_to is None:
        return None
    from_user = getattr(reply_to, "from_user", None)
    if from_user is None:
        return None
    return _exclude_none(
        {
            "message_id": getattr(reply_to, "message_id", None),
            "from_user_id": getattr(from_user, "id", None),
            "from_username": getattr(from_user, "username", None),
            "from_is_bot": getattr(from_user, "is_bot", None),
            "text": (getattr(reply_to, "text", "") or "")[:100],
        }
    )


def _build_enriched_prompt(
    content: str,
    message: Any,
    msg_type: str = "text",
    media_metadata: dict[str, Any] | None = None,
) -> str:
    """Build an enriched prompt with channel metadata appended as JSON.

    Inspired by bub's get_session_prompt pattern — lets the agent know
    who sent the message, which chat it came from, and how to reply.
    """
    user = getattr(message, "from_user", None) or getattr(message, "effective_user", None)
    chat = getattr(message, "chat", None)
    meta: dict[str, Any] = {
        "channel": "telegram",
        "chat_id": str(getattr(message, "chat_id", "")),
        "message_id": getattr(message, "message_id", None),
        "type": msg_type,
        "username": getattr(user, "username", None) if user else None,
        "full_name": getattr(user, "full_name", None)
        or ((getattr(user, "first_name", "") or "") + " " + (getattr(user, "last_name", "") or "")).strip()
        if user
        else None,
        "sender_id": str(getattr(user, "id", "")) if user else None,
        "sender_is_bot": getattr(user, "is_bot", None) if user else None,
        "chat_type": getattr(chat, "type", None) if chat else None,
    }
    if media_metadata:
        meta["media"] = media_metadata
    reply_meta = _extract_reply_metadata(message)
    if reply_meta:
        meta["reply_to_message"] = reply_meta
    date = getattr(message, "date", None)
    if date:
        meta["date"] = date.timestamp() if hasattr(date, "timestamp") else str(date)
    metadata_json = json.dumps(_exclude_none(meta), ensure_ascii=False)
    return f"{content}\n———————\n{metadata_json}"


class SessionManager:
    def __init__(self, agent_factory: Callable[[str], Any], session_timeout: int = 3600) -> None:
        self._agent_factory = agent_factory
        self._session_timeout = session_timeout
        self._sessions: dict[int, dict[str, TelegramSession]] = {}
        self._current_sessions: dict[int, str] = {}

    def get_or_create_session(self, chat_id: int) -> TelegramSession:
        self.prune_expired()
        current_id = self._current_sessions.get(chat_id)
        if current_id:
            session = self._sessions.get(chat_id, {}).get(current_id)
            if session:
                return session
        return self.create_session(chat_id)

    def create_session(self, chat_id: int) -> TelegramSession:
        from uuid import uuid4

        session_id = f"telegram-{chat_id}-{uuid4().hex[:8]}"
        agent = self._agent_factory(session_id)
        session = TelegramSession(session_id=session_id, agent=agent)
        self._sessions.setdefault(chat_id, {})[session_id] = session
        self._current_sessions[chat_id] = session_id
        return session

    def list_sessions(self, chat_id: int) -> list[TelegramSession]:
        self.prune_expired()
        return list(self._sessions.get(chat_id, {}).values())

    def switch_session(self, chat_id: int, session_id: str) -> bool:
        session = self._sessions.get(chat_id, {}).get(session_id)
        if not session:
            return False
        self._current_sessions[chat_id] = session_id
        return True

    def get_current_session_id(self, chat_id: int) -> str | None:
        return self._current_sessions.get(chat_id)

    def prune_expired(self) -> None:
        if self._session_timeout <= 0:
            return
        cutoff = datetime.now() - timedelta(seconds=self._session_timeout)
        for chat_id, sessions in list(self._sessions.items()):
            for session_id, session in list(sessions.items()):
                if session.last_used < cutoff:
                    sessions.pop(session_id, None)
            if not sessions:
                self._sessions.pop(chat_id, None)
                self._current_sessions.pop(chat_id, None)

    def update_session_timeout(self, timeout: int) -> None:
        self._session_timeout = timeout


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[int, deque[float]] = {}

    def allow(self, user_id: int) -> bool:
        if self._limit <= 0:
            return True
        now = datetime.now().timestamp()
        hits = self._hits.setdefault(user_id, deque())
        while hits and now - hits[0] > self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def update_limit(self, limit: int) -> None:
        self._limit = limit


class TelegramHandlers:
    def __init__(
        self,
        bot: TelegramBot,
        session_manager: SessionManager,
        auth: AuthMiddleware,
        rate_limiter: RateLimiter,
        work_dir: Path | None = None,
    ) -> None:
        self._bot = bot
        self._session_manager = session_manager
        self._auth = auth
        self._rate_limiter = rate_limiter
        self._work_dir = work_dir

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        await self._bot.send_text(
            update.effective_chat.id,
            "Welcome to AMCP Bot. Use /help to see available commands.",
        )

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        await self._bot.send_text(
            update.effective_chat.id,
            "\n".join(
                [
                    "Commands:",
                    "/start - Initialize bot",
                    "/help - Show commands",
                    "/status - Agent status",
                    "/session new|list|switch <id> - Manage sessions",
                    "/cancel - Cancel current operation",
                    "/ask <prompt> - Send a prompt",
                    "/skills - List skills",
                    "/activate <skill> - Activate a skill",
                    "/memory search <query> - Search memory",
                    "/config show|set <key> <value> - View/update config (admin)",
                    "/users list|add|remove <id> - Manage users (admin)",
                    "/logs <n> - Show recent logs (admin)",
                    "/shutdown - Stop the bot (admin)",
                ]
            ),
        )

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        chat_id = update.effective_chat.id
        sessions = self._session_manager.list_sessions(chat_id)
        current = self._session_manager.get_current_session_id(chat_id)
        await self._bot.send_text(
            chat_id,
            f"Sessions: {len(sessions)}\nCurrent session: {current or 'none'}",
        )

    async def handle_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        chat_id = update.effective_chat.id
        args = context.args or []
        if not args or args[0] == "list":
            sessions = self._session_manager.list_sessions(chat_id)
            lines = ["Sessions:"]
            current_id = self._session_manager.get_current_session_id(chat_id)
            for session in sessions:
                marker = "*" if session.session_id == current_id else "-"
                lines.append(f"{marker} {session.session_id}")
            await self._bot.send_text(chat_id, "\n".join(lines))
            return
        if args[0] == "new":
            session = self._session_manager.create_session(chat_id)
            await self._bot.send_text(chat_id, f"Created session: {session.session_id}")
            return
        if args[0] == "switch" and len(args) > 1:
            if self._session_manager.switch_session(chat_id, args[1]):
                await self._bot.send_text(chat_id, f"Switched to session: {args[1]}")
            else:
                await self._bot.send_text(chat_id, f"Unknown session: {args[1]}")
            return
        await self._bot.send_text(chat_id, "Usage: /session new|list|switch <id>")

    async def handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        chat_id = update.effective_chat.id
        cancelled, queued = self._bot.cancel_session(chat_id)
        if cancelled or queued:
            await self._bot.send_text(
                chat_id,
                f"Cancelled current task: {cancelled}. Cleared queued: {queued}.",
            )
        else:
            await self._bot.send_text(chat_id, "Nothing to cancel.")

    async def handle_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        prompt = " ".join(context.args or [])
        if not prompt:
            await self._bot.send_text(update.effective_chat.id, "Usage: /ask <prompt>")
            return
        message = update.message
        if message:
            prompt = _build_enriched_prompt(prompt, message)
        await self._bot.handle_prompt(update.effective_chat.id, update.effective_user.id, prompt)

    async def handle_skills(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        skill_manager = get_skill_manager()
        skill_manager.discover_skills(self._work_dir)
        skills = skill_manager.get_skills()
        if not skills:
            await self._bot.send_text(update.effective_chat.id, "No skills found.")
            return
        lines = ["Available skills:"]
        for skill in skills:
            lines.append(f"- {skill.name}: {skill.description}")
        await self._bot.send_text(update.effective_chat.id, "\n".join(lines))

    async def handle_activate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        name = " ".join(context.args or [])
        if not name:
            await self._bot.send_text(update.effective_chat.id, "Usage: /activate <skill>")
            return
        skill_manager = get_skill_manager()
        skill_manager.discover_skills(self._work_dir)
        if skill_manager.activate_skill(name):
            await self._bot.send_text(update.effective_chat.id, f"Activated skill: {name}")
        else:
            await self._bot.send_text(
                update.effective_chat.id,
                f"Unknown or disabled skill: {name}",
            )

    async def handle_memory(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        args = context.args or []
        if len(args) < 2 or args[0] != "search":
            await self._bot.send_text(update.effective_chat.id, "Usage: /memory search <query>")
            return
        query = " ".join(args[1:])
        memory_manager = get_memory_manager(self._work_dir)
        results = memory_manager.search(query)
        if not results:
            await self._bot.send_text(update.effective_chat.id, "No results found.")
            return
        lines = [f"Found {len(results)} results:"]
        for idx, result in enumerate(results, start=1):
            lines.append(f"{idx}. [{result.source}] {result.line_number}: {result.content}")
        await self._bot.send_text(update.effective_chat.id, "\n".join(lines))

    async def handle_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        args = context.args or []
        if not args or args[0] == "show":
            summary = self._bot.config_summary()
            await self._bot.send_text(update.effective_chat.id, summary)
            return
        if args[0] == "set" and len(args) >= 3:
            key = args[1]
            value = " ".join(args[2:])
            ok, message = self._bot.update_config_value(key, value)
            await self._bot.send_text(update.effective_chat.id, message)
            if ok:
                await self._bot.persist_config()
            return
        await self._bot.send_text(
            update.effective_chat.id,
            "Usage: /config show|set <key> <value>",
        )

    async def handle_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        args = context.args or []
        if not args or args[0] == "list":
            await self._bot.send_text(update.effective_chat.id, self._bot.users_summary())
            return
        if args[0] in {"add", "remove"} and len(args) > 1:
            try:
                user_id = int(args[1])
            except ValueError:
                await self._bot.send_text(update.effective_chat.id, "User ID must be numeric.")
                return
            if args[0] == "add":
                self._bot.add_allowed_user(user_id)
                await self._bot.persist_config()
                await self._bot.send_text(update.effective_chat.id, f"Added user: {user_id}")
                return
            self._bot.remove_allowed_user(user_id)
            await self._bot.persist_config()
            await self._bot.send_text(update.effective_chat.id, f"Removed user: {user_id}")
            return
        if len(args) > 2 and args[0] == "admin" and args[1] in {"add", "remove"}:
            try:
                user_id = int(args[2])
            except ValueError:
                await self._bot.send_text(update.effective_chat.id, "User ID must be numeric.")
                return
            if args[1] == "add":
                self._bot.add_admin_user(user_id)
                await self._bot.persist_config()
                await self._bot.send_text(update.effective_chat.id, f"Added admin: {user_id}")
                return
            self._bot.remove_admin_user(user_id)
            await self._bot.persist_config()
            await self._bot.send_text(update.effective_chat.id, f"Removed admin: {user_id}")
            return
        await self._bot.send_text(update.effective_chat.id, "Usage: /users list|add|remove <id>")

    async def handle_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        count = 20
        if context.args:
            try:
                count = int(context.args[0])
            except ValueError:
                await self._bot.send_text(update.effective_chat.id, "Usage: /logs <n>")
                return
        logs = self._bot.tail_logs(count)
        await self._bot.send_text(update.effective_chat.id, logs)

    async def handle_shutdown(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        await self._bot.send_text(update.effective_chat.id, "Shutting down.")
        await self._bot.stop()

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        if not self._rate_limiter.allow(update.effective_user.id):
            await self._bot.send_text(update.effective_chat.id, "Rate limit exceeded.")
            return
        message = update.message
        if not message:
            return
        msg_type = _message_type(message)
        if msg_type == "unknown":
            await self._bot.send_text(update.effective_chat.id, "Unsupported message type.")
            return
        if msg_type == "text":
            raw_text = message.text or ""
            enriched = _build_enriched_prompt(raw_text, message, msg_type)
            await self._bot.handle_prompt(
                update.effective_chat.id,
                update.effective_user.id,
                enriched,
            )
            return
        # Media messages
        text, msg_type, media_metadata = _parse_message(message)
        enriched = _build_enriched_prompt(text, message, msg_type, media_metadata)
        await self._bot.handle_media(
            update.effective_chat.id, update.effective_user.id, enriched, msg_type, media_metadata
        )

    async def handle_unknown(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_authorized(update):
            return
        await self._bot.send_text(update.effective_chat.id, "Unknown command. Use /help.")

    async def _ensure_authorized(self, update: Update) -> bool:
        user = update.effective_user
        chat = update.effective_chat
        if not user or not chat:
            return False
        if not self._auth.is_authorized(user.id):
            await self._bot.send_text(chat.id, "Access denied.")
            return False
        return True

    async def _ensure_admin(self, update: Update) -> bool:
        user = update.effective_user
        chat = update.effective_chat
        if not user or not chat:
            return False
        if not self._auth.is_admin(user.id):
            await self._bot.send_text(chat.id, "Admin access required.")
            return False
        return True
