from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..agent import Agent, BusyError, create_agent_by_name
from ..agent_spec import get_default_agent_spec
from ..config import load_config, save_config
from ..event_bus import EventType, get_event_bus
from ..memory import CONFIG_DIR, get_memory_manager
from ..memory_dream import MemoryDreamer
from ..multi_agent import get_agent_registry
from .auth import AuthMiddleware
from .config import TelegramConfig, normalize_dm_policy, normalize_group_policy
from .formatter import TelegramFormatter
from .handlers import RateLimiter, SessionManager, TelegramHandlers, TelegramQueuedMessage
from .scheduler import SCHEDULE_BLUEPRINTS, TelegramScheduledPrompt, TelegramScheduleStore

if TYPE_CHECKING:
    from telegram.ext import Application

try:
    from telegram import BotCommand
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
except ImportError:  # pragma: no cover - optional dependency
    BotCommand = None  # type: ignore[assignment]
    ApplicationBuilder = None  # type: ignore[assignment]
    CommandHandler = None  # type: ignore[assignment]
    MessageHandler = None  # type: ignore[assignment]
    filters = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

TELEGRAM_MEMORY_LOG_USER_LIMIT = 1000
TELEGRAM_MEMORY_LOG_AGENT_LIMIT = 2000
TELEGRAM_MEMORY_DREAM_INTERVAL_SECONDS = 60 * 60


@dataclass
class PairingRequest:
    code: str
    user_id: int
    chat_id: int
    username: str | None
    created_at: datetime


class TelegramBot:
    """Telegram bot that connects chat messages to an AMCP agent."""

    def __init__(
        self,
        token: str,
        allowed_users: set[int],
        admin_users: set[int] | None = None,
        *,
        agent_factory: Callable[[str], Agent] | None = None,
        work_dir: Path | None = None,
        config: TelegramConfig | None = None,
    ) -> None:
        if ApplicationBuilder is None:
            raise RuntimeError("python-telegram-bot is required. Install amcp[telegram].")

        self._token = token
        self._work_dir = work_dir
        self._config = config or TelegramConfig(enabled=True)
        self._config.bot_token = token
        self._auth = AuthMiddleware(
            allowed_users=set(allowed_users),
            admin_users=set(admin_users or []),
        )
        self._auth.allowed_users.update(self._auth.admin_users)
        self._config.allowed_users = sorted(self._auth.allowed_users)
        self._config.admin_users = sorted(self._auth.admin_users)
        self._formatter = TelegramFormatter(max_length=self._config.max_message_length)
        self._session_manager = SessionManager(
            agent_factory=agent_factory or self._default_agent_factory,
            session_timeout=self._config.session_timeout,
        )
        self._rate_limiter = RateLimiter(limit=self._config.rate_limit_messages)
        self._handlers = TelegramHandlers(
            bot=self,
            session_manager=self._session_manager,
            auth=self._auth,
            rate_limiter=self._rate_limiter,
            work_dir=self._work_dir,
        )
        self._application = self._build_application()
        self._stop_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._notification_handler_ids: list[str] = []
        self._skill_watcher: Any = None  # SkillWatcher (lazy import)
        self._typing_tasks: dict[int, asyncio.Task[None]] = {}
        self._pairing_requests: dict[str, PairingRequest] = {}
        self._scheduler: Any = None  # AssistantScheduler (lazy import)
        self._prompt_scheduler: Any = None  # TelegramPromptScheduler (lazy import)
        self._schedule_store = TelegramScheduleStore()
        self._session_boundary_locks: dict[int, asyncio.Lock] = {}
        self._memory_dream_task: asyncio.Task[None] | None = None
        self._memory_dream_interval_seconds = TELEGRAM_MEMORY_DREAM_INTERVAL_SECONDS

    @property
    def config(self) -> TelegramConfig:
        return self._config

    def config_summary(self) -> str:
        token_status = "set" if self._config.bot_token else "unset"
        return "\n".join(
            [
                f"enabled: {self._config.enabled}",
                f"bot_token: {token_status}",
                f"allowed_users: {len(self._config.allowed_users)}",
                f"admin_users: {len(self._config.admin_users)}",
                f"webhook_mode: {self._config.webhook_mode}",
                f"webhook_url: {self._config.webhook_url or ''}",
                f"max_message_length: {self._config.max_message_length}",
                f"rate_limit_messages: {self._config.rate_limit_messages}",
                f"session_timeout: {self._config.session_timeout}",
                f"dm_policy: {self._config.dm_policy}",
                f"group_policy: {self._config.group_policy}",
                f"group_allow_users: {len(self._config.group_allow_users)}",
                f"typing_indicator: {self._config.typing_indicator}",
                f"typing_interval_seconds: {self._config.typing_interval_seconds}",
                f"max_queue_size: {self._config.max_queue_size}",
            ]
        )

    def users_summary(self) -> str:
        allowed = ", ".join(str(u) for u in sorted(self._auth.allowed_users)) or "none"
        admins = ", ".join(str(u) for u in sorted(self._auth.admin_users)) or "none"
        return f"allowed_users: {allowed}\nadmin_users: {admins}"

    def add_allowed_user(self, user_id: int) -> None:
        self._auth.allowed_users.add(user_id)
        self._config.allowed_users = sorted(self._auth.allowed_users)

    def remove_allowed_user(self, user_id: int) -> None:
        self._auth.allowed_users.discard(user_id)
        self._config.allowed_users = sorted(self._auth.allowed_users)
        if user_id in self._auth.admin_users:
            self._auth.admin_users.discard(user_id)
            self._config.admin_users = sorted(self._auth.admin_users)

    def add_admin_user(self, user_id: int) -> None:
        self._auth.admin_users.add(user_id)
        self._auth.allowed_users.add(user_id)
        self._config.admin_users = sorted(self._auth.admin_users)
        self._config.allowed_users = sorted(self._auth.allowed_users)

    def remove_admin_user(self, user_id: int) -> None:
        self._auth.admin_users.discard(user_id)
        self._config.admin_users = sorted(self._auth.admin_users)

    def update_config_value(self, key: str, value: str) -> tuple[bool, str]:
        key_map = {
            "enabled": bool,
            "webhook_mode": bool,
            "webhook_url": str,
            "max_message_length": int,
            "rate_limit_messages": int,
            "session_timeout": int,
            "typing_indicator": bool,
            "typing_interval_seconds": int,
            "max_queue_size": int,
            "dm_policy": str,
            "group_policy": str,
        }
        if key not in key_map:
            return False, f"Unsupported config key: {key}"
        try:
            if key in {"dm_policy", "group_policy"}:
                parsed = normalize_dm_policy(value) if key == "dm_policy" else normalize_group_policy(value)
                if parsed != value.strip().lower():
                    return False, f"Invalid value for {key}."
            elif key_map[key] is bool:
                parsed = value.lower() in {"1", "true", "yes", "on"}
            elif key_map[key] is int:
                parsed = int(value)
                if key in {"typing_interval_seconds", "max_queue_size"} and parsed < 1:
                    return False, f"{key} must be >= 1."
            else:
                parsed = value
            setattr(self._config, key, parsed)
            if key == "max_message_length":
                self._formatter.max_length = parsed
            elif key == "rate_limit_messages":
                self._rate_limiter.update_limit(parsed)
            elif key == "session_timeout":
                self._session_manager.update_session_timeout(parsed)
            return True, f"Updated {key}."
        except ValueError:
            return False, f"Invalid value for {key}."

    def models_summary(self) -> str:
        """Return a user-facing summary of configured LLM provider profiles."""
        cfg = load_config()
        chat = cfg.chat
        if chat is None:
            return "No chat configuration found."

        if not chat.providers:
            lines = ["Configured providers:", "* current"]
            if chat.model:
                lines[-1] += f" — model={chat.model}"
            if chat.base_url:
                lines[-1] += f" — base_url={chat.base_url}"
            lines.append("Add [chat.providers.<name>] entries to config.toml to enable switching.")
            return "\n".join(lines)

        lines = ["Configured providers:"]
        for name, provider in sorted(chat.providers.items()):
            marker = "*" if name == chat.active_provider else "-"
            details = []
            if provider.api_type:
                details.append(f"api_type={provider.api_type}")
            if provider.model:
                details.append(f"model={provider.model}")
            if provider.base_url:
                details.append(f"base_url={provider.base_url}")
            suffix = f" — {'; '.join(details)}" if details else ""
            lines.append(f"{marker} {name}{suffix}")
        lines.append("Use /model use <name> to switch provider.")
        return "\n".join(lines)

    def use_model_provider(self, name: str) -> tuple[bool, str]:
        """Switch the active LLM provider profile and persist it to config.toml."""
        provider_name = name.strip()
        if not provider_name:
            return False, "Usage: /model use <name>"

        cfg = load_config()
        if cfg.chat is None:
            return False, "No chat configuration found."
        provider = cfg.chat.providers.get(provider_name)
        if provider is None:
            available = ", ".join(sorted(cfg.chat.providers)) or "none"
            return False, f"Unknown provider: {provider_name}. Available: {available}"

        cfg.chat.active_provider = provider_name
        cfg.chat.base_url = provider.base_url
        cfg.chat.model = provider.model
        cfg.chat.api_key = provider.api_key
        cfg.chat.api_type = provider.api_type
        cfg.chat.model_config = provider.model_config
        path = save_config(cfg)
        try:
            path.chmod(0o600)
        except OSError:
            logger.warning("Failed to set config file permissions.")
        model = provider.model or "unset"
        api_type = provider.api_type or "openai"
        return True, f"Switched provider to {provider_name} (api_type={api_type}, model={model})."

    async def persist_config(self) -> None:
        cfg = load_config()
        telegram_cfg = self._config
        if os.environ.get("AMCP_TELEGRAM_BOT_TOKEN"):
            telegram_cfg = replace(telegram_cfg, bot_token=None)
        cfg.telegram = telegram_cfg
        path = save_config(cfg)
        try:
            path.chmod(0o600)
        except OSError:
            logger.warning("Failed to set config file permissions.")

    async def start_polling(self) -> None:
        self._register_telegram_send_tool()
        self._register_telegram_schedule_tool()
        self._register_notifications()
        await self._start_skill_watcher()
        if self._config.assistant_mode:
            await self._start_assistant_scheduler()
        await self._start_prompt_scheduler()
        self._start_memory_dream_loop()
        await self._run_polling_loop()

    async def start_webhook(self, url: str, listen: str = "0.0.0.0", port: int = 8443) -> None:
        self._register_telegram_send_tool()
        self._register_telegram_schedule_tool()
        self._register_notifications()
        await self._start_skill_watcher()
        if self._config.assistant_mode:
            await self._start_assistant_scheduler()
        await self._start_prompt_scheduler()
        self._start_memory_dream_loop()
        await self._run_webhook_loop(url, listen=listen, port=port)

    async def stop(self) -> None:
        await self._stop_memory_dream_loop()
        if self._prompt_scheduler:
            await self._prompt_scheduler.stop()
            self._prompt_scheduler = None
        if self._scheduler:
            await self._scheduler.stop()
            self._scheduler = None
        if self._skill_watcher:
            await self._skill_watcher.stop()
            self._skill_watcher = None
        await self._stop_all_typing()
        if self._stop_event:
            self._stop_event.set()
        elif self._application:
            try:
                await self._application.stop()
                await self._application.shutdown()
            except Exception:
                logger.exception("Failed to stop Telegram application cleanly.")
        self._unregister_notifications()
        self._unregister_telegram_schedule_tool()
        self._unregister_telegram_send_tool()

    def cancel_session(self, chat_id: int) -> tuple[bool, bool]:
        session = self._session_manager.get_or_create_session(chat_id)
        cancelled = False
        if session.current_task and not session.current_task.done():
            session.current_task.cancel()
            cancelled = True
        queued = len(session.queue) > 0
        session.queue.clear()
        return cancelled, queued

    def _get_session_boundary_lock(self, chat_id: int) -> asyncio.Lock:
        lock = self._session_boundary_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_boundary_locks[chat_id] = lock
        return lock

    async def create_new_session(self, chat_id: int) -> Any:
        """Atomically flush and replace the current Telegram session."""
        async with self._get_session_boundary_lock(chat_id):
            old_session = self._session_manager.get_current_session(chat_id)
            if old_session:
                self._session_manager.abandon_current_session(chat_id)
                await self.flush_session_memory(chat_id, old_session)

            session = self._session_manager.create_session(chat_id)
            self._bind_session_memory(chat_id, session)
            return session

    def memory_project_root(self, chat_id: int) -> Path:
        """Return the isolated project-memory root for a Telegram chat."""
        return CONFIG_DIR / "telegram" / f"chat_{chat_id}"

    def _bind_session_memory(self, chat_id: int, session: Any) -> None:
        self._bind_agent_memory_context(chat_id, session.agent)

    def _bind_agent_memory_context(self, chat_id: int, agent: Any) -> None:
        context = getattr(agent, "execution_context", None)
        if isinstance(context, dict):
            context["memory_project_root"] = str(self.memory_project_root(chat_id))
            context["source"] = "telegram"
            context["telegram_chat_id"] = str(chat_id)

    def create_scheduled_prompt(
        self,
        chat_id: int,
        schedule: str,
        prompt: str,
        *,
        name: str | None = None,
        notify: bool = True,
        timeout: int = 900,
    ) -> tuple[bool, str]:
        """Create a persistent scheduled prompt for a Telegram chat."""
        try:
            job = self._schedule_store.create_job(
                chat_id=chat_id,
                schedule=schedule,
                prompt=prompt,
                name=name,
                notify=notify,
                timeout=timeout,
            )
        except ValueError as exc:
            return False, str(exc)
        return True, f"Created scheduled prompt {job.id}: {job.schedule}"

    def create_scheduled_blueprint(
        self,
        chat_id: int,
        blueprint: str,
        schedule: str,
        *,
        name: str | None = None,
        notify: bool = True,
        timeout: int = 900,
    ) -> tuple[bool, str]:
        """Create a persistent scheduled prompt from a built-in blueprint."""
        try:
            job = self._schedule_store.create_blueprint_job(
                chat_id=chat_id,
                blueprint=blueprint,
                schedule=schedule,
                name=name,
                notify=notify,
                timeout=timeout,
            )
        except ValueError as exc:
            return False, str(exc)
        return True, f"Created scheduled blueprint {job.blueprint} as {job.id}: {job.schedule}"

    def list_scheduled_prompts(self, chat_id: int) -> list[TelegramScheduledPrompt]:
        """List persistent scheduled prompts for a Telegram chat."""
        return self._schedule_store.list_jobs(chat_id)

    def delete_scheduled_prompt(self, chat_id: int, job_id: str) -> tuple[bool, str]:
        """Delete one persistent scheduled prompt for a Telegram chat."""
        if self._schedule_store.delete_job(chat_id, job_id):
            return True, f"Deleted scheduled prompt {job_id}."
        return False, f"Scheduled prompt not found: {job_id}"

    def list_schedule_blueprints(self) -> str:
        """Return a user-facing list of built-in schedule blueprints."""
        lines = ["Schedule blueprints:"]
        for name, blueprint in sorted(SCHEDULE_BLUEPRINTS.items()):
            lines.append(f"- {name}: {blueprint.description}")
        return "\n".join(lines)

    async def flush_session_memory(self, chat_id: int, session: Any) -> bool:
        """Flush durable memory for a Telegram session before it is replaced."""
        self._bind_session_memory(chat_id, session)
        flush = getattr(session.agent, "flush_memory", None)
        if not callable(flush):
            return False
        try:
            return bool(
                await asyncio.wait_for(
                    flush(work_dir=self._work_dir),
                    timeout=60,
                )
            )
        except Exception:
            logger.exception("Telegram memory flush failed.")
            return False

    def _start_memory_dream_loop(self) -> None:
        if self._memory_dream_task and not self._memory_dream_task.done():
            return
        self._memory_dream_task = asyncio.create_task(self._memory_dream_loop())

    async def _stop_memory_dream_loop(self) -> None:
        task = self._memory_dream_task
        if not task:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._memory_dream_task = None

    async def _memory_dream_loop(self) -> None:
        while True:
            await asyncio.sleep(self._memory_dream_interval_seconds)
            await self._run_memory_dream_once()

    async def _run_memory_dream_once(self) -> None:
        for chat_id in self._session_manager.list_chat_ids():
            project_root = self.memory_project_root(chat_id)
            try:
                result = await asyncio.to_thread(MemoryDreamer(project_root).run_once)
                logger.debug(
                    "Telegram memory dream chat=%s ran=%s updated=%s reason=%s",
                    chat_id,
                    result.ran,
                    result.updated,
                    result.reason,
                )
            except Exception:
                logger.exception("Telegram memory dream failed for chat %s.", chat_id)

    def create_pairing_request(self, user_id: int, chat_id: int, username: str | None = None) -> tuple[str, bool]:
        self._prune_pairing_requests()
        for request in self._pairing_requests.values():
            if request.user_id == user_id:
                request.chat_id = chat_id
                request.username = username
                return request.code, False

        if len(self._pairing_requests) >= self._config.pairing.max_pending:
            oldest = min(self._pairing_requests.values(), key=lambda item: item.created_at)
            self._pairing_requests.pop(oldest.code, None)

        alphabet = string.ascii_uppercase + string.digits
        code = ""
        while not code or code in self._pairing_requests:
            code = "".join(secrets.choice(alphabet) for _ in range(8))

        self._pairing_requests[code] = PairingRequest(
            code=code,
            user_id=user_id,
            chat_id=chat_id,
            username=username,
            created_at=datetime.now(),
        )
        return code, True

    def approve_pairing_code(self, code: str) -> tuple[bool, str]:
        self._prune_pairing_requests()
        normalized = code.strip().upper()
        if not normalized:
            return False, "Pairing code is required."
        request = self._pairing_requests.pop(normalized, None)
        if request is None:
            return False, "Pairing code not found or expired."
        self.add_allowed_user(request.user_id)
        return True, f"Approved Telegram user {request.user_id}."

    def list_pairing_requests(self) -> list[PairingRequest]:
        self._prune_pairing_requests()
        return sorted(self._pairing_requests.values(), key=lambda req: req.created_at)

    def _prune_pairing_requests(self) -> None:
        ttl = max(60, int(self._config.pairing.code_ttl_seconds))
        cutoff = datetime.now() - timedelta(seconds=ttl)
        for code, request in list(self._pairing_requests.items()):
            if request.created_at < cutoff:
                self._pairing_requests.pop(code, None)

    def _is_queue_full(self, session: Any) -> bool:
        max_queue_size = self._config.max_queue_size
        if max_queue_size <= 0:
            return False
        return len(session.queue) >= max_queue_size

    async def handle_prompt(self, chat_id: int, user_id: int, text: str) -> None:
        session = self._session_manager.get_or_create_session(chat_id)
        session.last_used = datetime.now()
        queued_message = TelegramQueuedMessage(chat_id=chat_id, user_id=user_id, text=text)

        if session.lock.locked():
            if self._is_queue_full(session):
                await self.send_text(chat_id, "Session queue is full. Please try again later.")
                return
            session.queue.append(queued_message)
            await self.send_text(chat_id, "Session busy. Your message was queued.")
            return

        generation = getattr(session, "generation", 0)
        async with session.lock:
            await self._process_message(session, queued_message)
            while session.queue and getattr(session, "generation", 0) == generation:
                next_message = session.queue.popleft()
                await self._process_message(session, next_message)

    async def handle_media(
        self, chat_id: int, user_id: int, text: str, message_type: str, metadata: dict[str, Any] | None
    ) -> None:
        session = self._session_manager.get_or_create_session(chat_id)
        session.last_used = datetime.now()
        queued_message = TelegramQueuedMessage(
            chat_id=chat_id, user_id=user_id, text=text, message_type=message_type, metadata=metadata
        )

        if session.lock.locked():
            if self._is_queue_full(session):
                await self.send_text(chat_id, "Session queue is full. Please try again later.")
                return
            session.queue.append(queued_message)
            await self.send_text(chat_id, "Session busy. Your message was queued.")
            return

        generation = getattr(session, "generation", 0)
        async with session.lock:
            await self._process_message(session, queued_message)
            while session.queue and getattr(session, "generation", 0) == generation:
                next_message = session.queue.popleft()
                await self._process_message(session, next_message)

    async def send_text(self, chat_id: int, text: str) -> None:
        await self._application.bot.send_message(chat_id=chat_id, text=text)

    async def send_markdown(self, chat_id: int, text: str) -> None:
        await self._application.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )

    async def send_notification(self, text: str) -> None:
        if self._loop and asyncio.get_running_loop() is not self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._send_notification_inner(text),
                self._loop,
            )
            await asyncio.wrap_future(future)
            return
        await self._send_notification_inner(text)

    def tail_logs(self, lines: int) -> str:
        log_path = Path.home() / ".config" / "amcp" / "logs" / "amcp.log"
        if not log_path.exists():
            return "No log file found."
        content = log_path.read_text(encoding="utf-8").splitlines()
        return "\n".join(content[-lines:]) if content else "No log entries."

    async def _send_notification_inner(self, text: str) -> None:
        for user_id in sorted(self._auth.allowed_users):
            await self.send_text(user_id, text)

    async def _process_message(self, session: Any, message: TelegramQueuedMessage) -> None:
        generation = getattr(session, "generation", 0)
        task: asyncio.Task | None = None
        self._bind_session_memory(message.chat_id, session)
        async with self._typing_session(message.chat_id):
            try:
                task = asyncio.create_task(
                    session.agent.run(
                        user_input=message.text,
                        work_dir=self._work_dir,
                        stream=False,
                        show_progress=False,
                        queue_if_busy=False,
                    )
                )
                session.current_task = task
                response = await task
            except asyncio.CancelledError:
                if getattr(session, "generation", 0) == generation:
                    await self.send_text(message.chat_id, "Request cancelled.")
                return
            except BusyError:
                if getattr(session, "generation", 0) != generation:
                    return
                if self._is_queue_full(session):
                    await self.send_text(message.chat_id, "Session queue is full. Please try again later.")
                else:
                    session.queue.appendleft(message)
                    await self.send_text(message.chat_id, "Session busy. Your message was queued.")
                return
            except Exception as exc:
                logger.exception("Failed to process Telegram message.")
                if getattr(session, "generation", 0) == generation:
                    await self.send_markdown(message.chat_id, self._formatter.format_error(str(exc)))
                return
            finally:
                if getattr(session, "current_task", None) is task:
                    session.current_task = None

            response_text = response or ""
            if getattr(session, "generation", 0) != generation:
                return
            if response_text:
                for chunk in self._formatter.format_response(response_text):
                    if getattr(session, "generation", 0) != generation:
                        return
                    await self.send_markdown(message.chat_id, chunk)

        if getattr(session, "generation", 0) != generation:
            return
        memory_manager = get_memory_manager(self.memory_project_root(message.chat_id))
        memory_manager.append_history(
            content=self._format_telegram_history_entry(message, response_text),
            session_id=session.session_id,
            tags=["telegram", "conversation"],
            scope="project",
        )

    @staticmethod
    def _trim_memory_log_text(text: str, limit: int) -> str:
        stripped = text.strip()
        if len(stripped) <= limit:
            return stripped
        return stripped[:limit].rstrip() + "\n[... truncated ...]"

    def _format_telegram_history_entry(self, message: TelegramQueuedMessage, response_text: str) -> str:
        user = self._trim_memory_log_text(message.text, TELEGRAM_MEMORY_LOG_USER_LIMIT)
        agent = self._trim_memory_log_text(response_text, TELEGRAM_MEMORY_LOG_AGENT_LIMIT)
        return f"[Telegram] chat={message.chat_id} user={message.user_id}\n\nUser:\n{user}\n\nAgent:\n{agent}"

    def _build_application(self) -> Application:
        application = ApplicationBuilder().token(self._token).post_init(self._post_init).build()
        application.add_handler(CommandHandler("start", self._handlers.handle_start))
        application.add_handler(CommandHandler("help", self._handlers.handle_help))
        application.add_handler(CommandHandler("status", self._handlers.handle_status))
        application.add_handler(CommandHandler("session", self._handlers.handle_session))
        application.add_handler(CommandHandler("new", self._handlers.handle_new))
        application.add_handler(CommandHandler("cancel", self._handlers.handle_cancel))
        application.add_handler(CommandHandler("ask", self._handlers.handle_ask))
        application.add_handler(CommandHandler("skills", self._handlers.handle_skills))
        application.add_handler(CommandHandler("activate", self._handlers.handle_activate))
        application.add_handler(CommandHandler("memory", self._handlers.handle_memory))
        application.add_handler(CommandHandler("models", self._handlers.handle_models))
        application.add_handler(CommandHandler("model", self._handlers.handle_model))
        application.add_handler(CommandHandler("config", self._handlers.handle_config))
        application.add_handler(CommandHandler("users", self._handlers.handle_users))
        application.add_handler(CommandHandler("pair", self._handlers.handle_pair))
        application.add_handler(CommandHandler("logs", self._handlers.handle_logs))
        application.add_handler(CommandHandler("shutdown", self._handlers.handle_shutdown))
        # Handle /skill:<name> commands (not supported by CommandHandler due to colon)
        application.add_handler(
            MessageHandler(
                filters.TEXT & filters.Regex(r"^/skill:[a-zA-Z0-9_-]+"),
                self._handlers.handle_skill,
            )
        )
        application.add_handler(
            MessageHandler(
                (
                    filters.TEXT
                    | filters.PHOTO
                    | filters.AUDIO
                    | filters.VIDEO
                    | filters.VOICE
                    | filters.Document.ALL
                    | filters.Sticker.ALL
                    | filters.VIDEO_NOTE
                )
                & ~filters.COMMAND,
                self._handlers.handle_message,
            )
        )
        application.add_handler(MessageHandler(filters.COMMAND, self._handlers.handle_unknown))
        return application

    def _get_user_bot_commands(self) -> list[BotCommand]:
        """Return user-facing commands to register in Telegram's bot menu.

        Admin-only commands (config, users, pair, logs, shutdown) and helper
        commands better discovered via /help (cancel, ask, activate, memory) are
        intentionally omitted; /help already lists them.
        """
        return [
            BotCommand("start", "Initialize the bot"),
            BotCommand("help", "Show available commands"),
            BotCommand("status", "Show agent and session status"),
            BotCommand("new", "Start a new conversation session"),
            BotCommand("session", "Manage sessions (new|list|switch)"),
            BotCommand("skills", "List and manage skills"),
            BotCommand("models", "List configured LLM providers"),
        ]

    async def _post_init(self, application: Application) -> None:
        """Register user-facing commands with Telegram's bot menu after init."""
        if BotCommand is None:
            return
        try:
            await application.bot.set_my_commands(self._get_user_bot_commands())
            logger.info("Registered Telegram bot menu commands")
        except Exception:
            logger.warning("Failed to register Telegram bot menu commands", exc_info=True)

    async def _run_polling_loop(self) -> None:
        updater = getattr(self._application, "updater", None)
        if updater is None or not hasattr(updater, "start_polling"):
            await asyncio.to_thread(self._application.run_polling)
            return
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        try:
            await self._application.initialize()
            await self._application.start()
        except AttributeError:
            await asyncio.to_thread(self._application.run_polling)
            return
        await updater.start_polling()
        await self._stop_event.wait()
        await updater.stop()
        await self._application.stop()
        await self._application.shutdown()

    async def _run_webhook_loop(self, url: str, listen: str, port: int) -> None:
        updater = getattr(self._application, "updater", None)
        if updater is None or not hasattr(updater, "start_webhook"):
            await asyncio.to_thread(
                self._application.run_webhook,
                listen=listen,
                port=port,
                webhook_url=url,
            )
            return
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        try:
            await self._application.initialize()
            await self._application.start()
        except AttributeError:
            await asyncio.to_thread(
                self._application.run_webhook,
                listen=listen,
                port=port,
                webhook_url=url,
            )
            return
        await updater.start_webhook(listen=listen, port=port, webhook_url=url)
        await self._stop_event.wait()
        await updater.stop()
        await self._application.stop()
        await self._application.shutdown()

    def _register_telegram_send_tool(self) -> None:
        """Register the TelegramSendTool with the global tool registry."""
        from ..tools import get_tool_registry
        from .tools import TelegramSendTool

        registry = get_tool_registry()
        if registry.get_tool("telegram_send") is None:
            tool = TelegramSendTool(bot_token=self._token)
            registry.register(tool)
            logger.info("Registered telegram_send tool")

    def _unregister_telegram_send_tool(self) -> None:
        """Unregister the TelegramSendTool from the global tool registry."""
        from ..tools import get_tool_registry

        registry = get_tool_registry()
        if registry.get_tool("telegram_send") is not None:
            registry.unregister("telegram_send")
            logger.info("Unregistered telegram_send tool")

    def _register_telegram_schedule_tool(self) -> None:
        """Register the TelegramScheduleTool with the global tool registry."""
        from ..tools import get_tool_registry
        from .tools import TelegramScheduleTool

        registry = get_tool_registry()
        if registry.get_tool("telegram_schedule") is None:
            registry.register(TelegramScheduleTool(self._schedule_store))
            logger.info("Registered telegram_schedule tool")

    def _unregister_telegram_schedule_tool(self) -> None:
        """Unregister the TelegramScheduleTool from the global tool registry."""
        from ..tools import get_tool_registry

        registry = get_tool_registry()
        if registry.get_tool("telegram_schedule") is not None:
            registry.unregister("telegram_schedule")
            logger.info("Unregistered telegram_schedule tool")

    def _register_notifications(self) -> None:
        if not self._config.notifications:
            return
        bus = get_event_bus()
        if self._config.notifications.task_completions:
            self._notification_handler_ids.append(bus.subscribe(EventType.TASK_COMPLETED, self._on_task_completed))
        if self._config.notifications.error_alerts:
            self._notification_handler_ids.append(bus.subscribe(EventType.AGENT_ERROR, self._on_agent_error))
            self._notification_handler_ids.append(bus.subscribe(EventType.TOOL_ERROR, self._on_tool_error))

    def _unregister_notifications(self) -> None:
        bus = get_event_bus()
        for handler_id in self._notification_handler_ids:
            bus.unsubscribe(handler_id)
        self._notification_handler_ids = []

    async def _on_task_completed(self, event: Any) -> None:
        description = event.data.get("description", "")
        duration = event.data.get("duration_ms", "")
        result = event.data.get("result", "")
        message = f"Task completed.\nDescription: {description}\nDuration: {duration}\nResult: {str(result)[:500]}"
        await self.send_notification(message)

    async def _on_agent_error(self, event: Any) -> None:
        error = event.data.get("error", "")
        session_id = event.session_id or "unknown"
        message = f"Agent error.\nSession: {session_id}\nError: {str(error)[:500]}"
        await self.send_notification(message)

    async def _on_tool_error(self, event: Any) -> None:
        error = event.data.get("error", "")
        tool = event.data.get("tool_name", "")
        message = f"Tool error.\nTool: {tool}\nError: {str(error)[:500]}"
        await self.send_notification(message)

    def _default_agent_factory(self, session_id: str) -> Agent:
        cfg = load_config()
        if cfg.chat and cfg.chat.default_agent:
            registry = get_agent_registry()
            if cfg.chat.default_agent in registry.list_agents():
                return create_agent_by_name(cfg.chat.default_agent, session_id=session_id)
        spec = get_default_agent_spec()
        return Agent(spec, session_id=session_id)

    async def _start_skill_watcher(self) -> None:
        """Start skill hot-reload watcher."""
        from ..skills import SkillWatcher, get_skill_manager

        mgr = get_skill_manager()
        self._skill_watcher = SkillWatcher(mgr)
        await self._skill_watcher.start(project_root=self._work_dir)
        logger.info("Telegram: SkillWatcher started for hot reload")

    async def _start_assistant_scheduler(self) -> None:
        """Start the assistant scheduler for cron-triggered skills."""
        from ..skills import get_skill_manager
        from .scheduler import AssistantScheduler

        mgr = get_skill_manager()
        self._scheduler = AssistantScheduler(
            skill_manager=mgr,
            agent_factory=self._session_manager._agent_factory,
            send_notification=self.send_notification,
            work_dir=self._work_dir,
        )
        await self._scheduler.start()
        logger.info("Telegram: AssistantScheduler started")

    async def _start_prompt_scheduler(self) -> None:
        """Start the internal scheduler for persistent Telegram prompt jobs."""
        from .scheduler import TelegramPromptScheduler

        if self._prompt_scheduler:
            return
        self._prompt_scheduler = TelegramPromptScheduler(
            store=self._schedule_store,
            agent_factory=self._session_manager._agent_factory,
            send_chat=self.send_text,
            bind_agent_context=self._bind_agent_memory_context,
            work_dir=self._work_dir,
        )
        await self._prompt_scheduler.start()
        logger.info("Telegram: PromptScheduler started")

    async def _start_typing(self, chat_id: int) -> None:
        if not self._config.typing_indicator:
            return
        await self._stop_typing(chat_id)
        await self._send_typing_action(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    async def _stop_typing(self, chat_id: int) -> None:
        task = self._typing_tasks.pop(chat_id, None)
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _stop_all_typing(self) -> None:
        chat_ids = list(self._typing_tasks)
        for chat_id in chat_ids:
            await self._stop_typing(chat_id)

    @contextlib.asynccontextmanager
    async def _typing_session(self, chat_id: int):
        await self._start_typing(chat_id)
        try:
            yield
        finally:
            await self._stop_typing(chat_id)

    async def _send_typing_action(self, chat_id: int) -> bool:
        try:
            await self._application.bot.send_chat_action(chat_id=chat_id, action="typing")
            return True
        except Exception as exc:
            logger.warning("Typing action failed for chat %s: %s", chat_id, exc)
            return False

    async def _typing_loop(self, chat_id: int) -> None:
        interval = max(1, int(self._config.typing_interval_seconds))
        try:
            while True:
                await asyncio.sleep(interval)
                await self._send_typing_action(chat_id)
        except asyncio.CancelledError:
            return
