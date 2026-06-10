from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..agent import Agent, BusyError, create_agent_by_name
from ..agent_spec import get_default_agent_spec
from ..config import CONFIG_FILE, load_config, save_config
from ..event_bus import EventType, get_event_bus
from ..mcp_client import list_mcp_tools
from ..memory import get_memory_manager
from ..multi_agent import get_agent_registry
from .auth import AuthMiddleware
from .config import TelegramConfig, normalize_dm_policy, normalize_group_policy
from .formatter import TelegramFormatter
from .handlers import RateLimiter, SessionManager, TelegramHandlers, TelegramQueuedMessage

if TYPE_CHECKING:
    from telegram.ext import Application

try:
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
except ImportError:  # pragma: no cover - optional dependency
    ApplicationBuilder = None  # type: ignore[assignment]
    CommandHandler = None  # type: ignore[assignment]
    MessageHandler = None  # type: ignore[assignment]
    filters = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


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

    async def refresh_mcp_servers(self) -> str:
        """Reload MCP configuration and probe server availability."""
        cfg = load_config()
        chat_cfg = cfg.chat

        if chat_cfg and chat_cfg.mcp_tools_enabled is False:
            return "MCP reload skipped: mcp_tools_enabled=false."

        missing: list[str] = []
        if chat_cfg and chat_cfg.mcp_servers:
            selected = [name for name in chat_cfg.mcp_servers if name in cfg.servers]
            missing = [name for name in chat_cfg.mcp_servers if name not in cfg.servers]
        else:
            selected = list(cfg.servers.keys())

        if not selected:
            if missing:
                return f"MCP reload: no valid servers (missing config: {', '.join(missing)})."
            return (
                f"MCP reload: no configured servers in {CONFIG_FILE}. "
                "Check whether Telegram process is using the expected config path."
            )

        async def _probe(server_name: str) -> tuple[str, int, str | None]:
            try:
                tools = await list_mcp_tools(cfg.servers[server_name])
                return server_name, len(tools), None
            except Exception as exc:
                error = str(exc).replace("\n", " ").strip()
                return server_name, 0, error

        results = await asyncio.gather(*(_probe(name) for name in selected))

        ready = [result for result in results if result[2] is None]
        failed = [result for result in results if result[2] is not None]
        total_tools = sum(tool_count for _, tool_count, _ in ready)

        summary = f"MCP reloaded: {len(ready)}/{len(selected)} servers ready, {total_tools} tools discovered."
        details: list[str] = []
        if missing:
            details.append(f"missing config: {', '.join(missing)}")
        if failed:
            failures = ", ".join(f"{name} ({(err or 'unknown error')[:120]})" for name, _, err in failed)
            details.append(f"failed: {failures}")
        if details:
            summary += "\n" + "\n".join(details)
        return summary

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

    async def persist_config(self) -> None:
        cfg = load_config()
        cfg.telegram = self._config
        path = save_config(cfg)
        try:
            path.chmod(0o600)
        except OSError:
            logger.warning("Failed to set config file permissions.")

    async def start_polling(self) -> None:
        self._register_telegram_send_tool()
        self._register_notifications()
        await self._start_skill_watcher()
        if self._config.assistant_mode:
            await self._start_assistant_scheduler()
        await self._run_polling_loop()

    async def start_webhook(self, url: str, listen: str = "0.0.0.0", port: int = 8443) -> None:
        self._register_telegram_send_tool()
        self._register_notifications()
        await self._start_skill_watcher()
        if self._config.assistant_mode:
            await self._start_assistant_scheduler()
        await self._run_webhook_loop(url, listen=listen, port=port)

    async def stop(self) -> None:
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

        async with session.lock:
            await self._process_message(session, queued_message)
            while session.queue:
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

        async with session.lock:
            await self._process_message(session, queued_message)
            while session.queue:
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
        await self._start_typing(message.chat_id)
        try:
            session.current_task = asyncio.create_task(
                session.agent.run(
                    user_input=message.text,
                    work_dir=self._work_dir,
                    stream=False,
                    show_progress=False,
                    queue_if_busy=False,
                )
            )
            response = await session.current_task
        except asyncio.CancelledError:
            await self.send_text(message.chat_id, "Request cancelled.")
            return
        except BusyError:
            if self._is_queue_full(session):
                await self.send_text(message.chat_id, "Session queue is full. Please try again later.")
            else:
                session.queue.appendleft(message)
                await self.send_text(message.chat_id, "Session busy. Your message was queued.")
            return
        except Exception as exc:
            logger.exception("Failed to process Telegram message.")
            await self.send_markdown(message.chat_id, self._formatter.format_error(str(exc)))
            return
        finally:
            session.current_task = None
            await self._stop_typing(message.chat_id)

        response_text = response or ""
        if response_text:
            for chunk in self._formatter.format_response(response_text):
                await self.send_markdown(message.chat_id, chunk)

        memory_manager = get_memory_manager(self._work_dir)
        memory_manager.append_history(
            content=(f"[Telegram] User {message.user_id}: {message.text[:200]}\nAgent: {response_text[:300]}"),
            session_id=session.session_id,
            tags=["telegram", "conversation"],
            scope="project",
        )

    def _build_application(self) -> Application:
        application = ApplicationBuilder().token(self._token).build()
        application.add_handler(CommandHandler("start", self._handlers.handle_start))
        application.add_handler(CommandHandler("help", self._handlers.handle_help))
        application.add_handler(CommandHandler("status", self._handlers.handle_status))
        application.add_handler(CommandHandler("session", self._handlers.handle_session))
        application.add_handler(CommandHandler("cancel", self._handlers.handle_cancel))
        application.add_handler(CommandHandler("ask", self._handlers.handle_ask))
        application.add_handler(CommandHandler("skills", self._handlers.handle_skills))
        application.add_handler(CommandHandler("activate", self._handlers.handle_activate))
        application.add_handler(CommandHandler("memory", self._handlers.handle_memory))
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

    async def _start_typing(self, chat_id: int) -> None:
        if not self._config.typing_indicator:
            return
        await self._stop_typing(chat_id)
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

    async def _typing_loop(self, chat_id: int) -> None:
        interval = max(1, int(self._config.typing_interval_seconds))
        try:
            while True:
                await self._application.bot.send_chat_action(chat_id=chat_id, action="typing")
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug("Typing loop stopped for chat %s: %s", chat_id, exc)
