import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from amcp.telegram.auth import AuthMiddleware
from amcp.telegram.config import TelegramConfig, TelegramGroupConfig, TelegramPairingConfig, TelegramTopicConfig
from amcp.telegram.formatter import TelegramFormatter
from amcp.telegram.handlers import (
    RateLimiter,
    SessionManager,
    TelegramHandlers,
    TelegramQueuedMessage,
    _build_enriched_prompt,
    _exclude_none,
    _extract_reply_metadata,
)


class _FakeAgent:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


class _FakeBot:
    def __init__(self, config: TelegramConfig) -> None:
        self.config = config
        self.pairing_requests: list[tuple[int, int, str | None]] = []
        self.sent_texts: list[tuple[int, str]] = []
        self.prompts: list[tuple[int, int, str]] = []

    def create_pairing_request(self, user_id: int, chat_id: int, username: str | None = None):
        self.pairing_requests.append((user_id, chat_id, username))
        return "PAIRCODE", True

    async def send_text(self, chat_id: int, text: str) -> None:
        self.sent_texts.append((chat_id, text))

    async def handle_prompt(self, chat_id: int, user_id: int, text: str) -> None:
        self.prompts.append((chat_id, user_id, text))

    def cancel_session(self, chat_id: int):
        return False, False


def test_auth_middleware():
    auth = AuthMiddleware(allowed_users={1, 2}, admin_users={2})
    assert auth.is_authorized(1)
    assert not auth.is_authorized(3)
    assert auth.is_admin(2)
    assert not auth.is_admin(1)


def test_formatter_escapes_markdown():
    formatter = TelegramFormatter(max_length=4096)
    chunks = formatter.format_response("Hello *world*!")
    assert chunks == ["Hello \\*world\\*\\!"]


def test_formatter_handles_code_block():
    formatter = TelegramFormatter(max_length=4096)
    chunks = formatter.format_response("```python\nprint('hi')\n```")
    assert chunks[0].startswith("```python")
    assert chunks[0].endswith("```")


def test_formatter_splits_long_text():
    formatter = TelegramFormatter(max_length=10)
    chunks = formatter.format_response("1234567890 123")
    assert all(len(chunk) <= 10 for chunk in chunks)


def test_session_manager_creates_sessions():
    manager = SessionManager(agent_factory=_FakeAgent, session_timeout=60)
    session = manager.get_or_create_session(123)
    assert session.session_id.startswith("telegram-123-")
    session2 = manager.create_session(123)
    assert manager.switch_session(123, session2.session_id)
    assert manager.get_current_session_id(123) == session2.session_id


def test_handle_new_uses_shared_session_command():
    async def _run():
        handlers, fake_bot = _make_handlers(TelegramConfig(), allowed_users={42})
        message = _make_message(text="/new", user_id=42)
        update = SimpleNamespace(
            effective_chat=message.chat,
            effective_user=message.from_user,
            message=message,
        )

        await handlers.handle_new(update, SimpleNamespace(args=[]))

        assert fake_bot.sent_texts
        assert fake_bot.sent_texts[-1][1].startswith("Created session: telegram-123-")

    asyncio.run(_run())


def test_handle_session_switch_uses_shared_session_command():
    async def _run():
        handlers, fake_bot = _make_handlers(TelegramConfig(), allowed_users={42})
        message = _make_message(text="/session", user_id=42)
        update = SimpleNamespace(
            effective_chat=message.chat,
            effective_user=message.from_user,
            message=message,
        )
        session = handlers._session_manager.create_session(123)

        await handlers.handle_session(update, SimpleNamespace(args=["switch", session.session_id]))

        assert fake_bot.sent_texts[-1] == (123, f"Switched to session: {session.session_id}")

    asyncio.run(_run())


# --- Metadata injection tests ---


def test_exclude_none_removes_none():
    result = _exclude_none({"a": 1, "b": None, "c": "hello", "d": None})
    assert result == {"a": 1, "c": "hello"}


def test_exclude_none_keeps_falsy():
    result = _exclude_none({"a": 0, "b": "", "c": False, "d": None})
    assert result == {"a": 0, "b": "", "c": False}


def _make_message(
    text="hello",
    chat_id=123,
    message_id=10,
    reply_to=None,
    *,
    chat_type="private",
    username="tester",
    user_id=42,
    entities=None,
    caption=None,
    caption_entities=None,
    thread_id=None,
    bot_username="amcp_bot",
    bot_id=700,
):
    user = SimpleNamespace(
        id=user_id,
        username=username,
        full_name="Test User",
        first_name="Test",
        last_name="User",
        is_bot=False,
    )
    chat = SimpleNamespace(id=chat_id, type=chat_type)
    bot = SimpleNamespace(id=bot_id, username=bot_username)
    return SimpleNamespace(
        chat_id=chat_id,
        chat=chat,
        message_id=message_id,
        text=text,
        caption=caption,
        entities=entities or [],
        caption_entities=caption_entities or [],
        from_user=user,
        reply_to_message=reply_to,
        message_thread_id=thread_id,
        date=None,
        get_bot=lambda: bot,
    )


def test_build_enriched_prompt_includes_separator():
    msg = _make_message(text="hello world")
    result = _build_enriched_prompt("hello world", msg)
    assert "\u2014\u2014\u2014\u2014\u2014\u2014\u2014" in result
    content, meta_json = result.split("\n\u2014\u2014\u2014\u2014\u2014\u2014\u2014\n", 1)
    assert content == "hello world"
    data = json.loads(meta_json)
    assert data["channel"] == "telegram"
    assert data["chat_id"] == "123"
    assert data["message_id"] == 10
    assert data["type"] == "text"
    assert data["sender_id"] == "42"
    assert data["sender_is_bot"] is False
    assert data["username"] == "tester"
    assert data["chat_type"] == "private"


def test_build_enriched_prompt_assistant_mode_adds_web_guidance():
    msg = _make_message(text="latest FastAPI changes")
    result = _build_enriched_prompt("latest FastAPI changes", msg, assistant_mode=True)
    content, meta_json = result.split("\n\u2014\u2014\u2014\u2014\u2014\u2014\u2014\n", 1)
    data = json.loads(meta_json)

    assert "[Telegram assistant mode]" in content
    assert "web_search" in content
    assert "web_fetch" in content
    assert data["assistant_mode"] is True
    assert data["network_tools"] == ["web_search", "web_fetch"]


def test_build_enriched_prompt_with_media_metadata():
    msg = _make_message(text="[Photo]")
    media_meta = {"file_id": "abc123", "width": 800, "height": 600}
    result = _build_enriched_prompt("[Photo]", msg, "photo", media_meta)
    _, meta_json = result.split("\n\u2014\u2014\u2014\u2014\u2014\u2014\u2014\n", 1)
    data = json.loads(meta_json)
    assert data["type"] == "photo"
    assert data["media"]["file_id"] == "abc123"


def test_extract_reply_metadata_none_when_no_reply():
    msg = _make_message()
    assert _extract_reply_metadata(msg) is None


def test_extract_reply_metadata_with_reply():
    reply_user = SimpleNamespace(id=99, username="bot_user", is_bot=True)
    reply_msg = SimpleNamespace(
        message_id=5,
        text="original message",
        from_user=reply_user,
    )
    msg = _make_message(reply_to=reply_msg)
    result = _extract_reply_metadata(msg)
    assert result is not None
    assert result["message_id"] == 5
    assert result["from_user_id"] == 99
    assert result["from_username"] == "bot_user"
    assert result["from_is_bot"] is True
    assert result["text"] == "original message"


def test_build_enriched_prompt_with_reply():
    reply_user = SimpleNamespace(id=99, username="bot_user", is_bot=True)
    reply_msg = SimpleNamespace(
        message_id=5,
        text="original",
        from_user=reply_user,
    )
    msg = _make_message(reply_to=reply_msg)
    result = _build_enriched_prompt("replying", msg)
    _, meta_json = result.split("\n\u2014\u2014\u2014\u2014\u2014\u2014\u2014\n", 1)
    data = json.loads(meta_json)
    assert "reply_to_message" in data
    reply = data["reply_to_message"]
    assert reply["message_id"] == 5
    assert reply["from_is_bot"] is True


def _make_handlers(config: TelegramConfig, allowed_users: set[int] | None = None):
    fake_bot = _FakeBot(config)
    manager = SessionManager(agent_factory=_FakeAgent, session_timeout=60)
    handlers = TelegramHandlers(
        bot=fake_bot,
        session_manager=manager,
        auth=AuthMiddleware(allowed_users=allowed_users or set(), admin_users=set()),
        rate_limiter=RateLimiter(limit=100),
    )
    return handlers, fake_bot


def test_message_access_dm_pairing_generates_code():
    handlers, fake_bot = _make_handlers(
        TelegramConfig(dm_policy="pairing", pairing=TelegramPairingConfig(enabled=True)),
        allowed_users=set(),
    )
    message = _make_message(chat_type="private", user_id=222, username="new_user")

    decision = handlers._evaluate_message_access(message, 222)

    assert decision.allowed is False
    assert decision.pairing_code == "PAIRCODE"
    assert fake_bot.pairing_requests == [(222, 123, "new_user")]


def test_message_access_group_mention_policy_requires_mention():
    handlers, _ = _make_handlers(TelegramConfig(group_policy="mention"), allowed_users=set())

    plain_message = _make_message(chat_type="supergroup", chat_id=-1001, text="hello")
    decision_plain = handlers._evaluate_message_access(plain_message, 42)
    assert decision_plain.allowed is False

    mention_message = _make_message(chat_type="supergroup", chat_id=-1001, text="@amcp_bot hello")
    decision_mention = handlers._evaluate_message_access(mention_message, 42)
    assert decision_mention.allowed is True
    assert decision_mention.was_mentioned is True


def test_message_access_group_reply_to_bot_counts_as_mention():
    handlers, _ = _make_handlers(TelegramConfig(group_policy="mention"), allowed_users=set())
    reply_to = SimpleNamespace(from_user=SimpleNamespace(id=700, is_bot=True), text="prev")
    message = _make_message(chat_type="group", chat_id=-1001, text="reply", reply_to=reply_to)

    decision = handlers._evaluate_message_access(message, 42)

    assert decision.allowed is True
    assert decision.was_mentioned is True


def test_message_access_topic_override_precedence():
    group_cfg = TelegramGroupConfig(
        group_policy="allowlist",
        allow_users=[10],
        topics={"42": TelegramTopicConfig(group_policy="open", require_mention=False)},
    )
    cfg = TelegramConfig(group_policy="mention", groups={"-1001": group_cfg})
    handlers, _ = _make_handlers(cfg, allowed_users=set())

    topic_message = _make_message(chat_type="supergroup", chat_id=-1001, thread_id=42, user_id=99)
    non_topic_message = _make_message(chat_type="supergroup", chat_id=-1001, thread_id=43, user_id=99)

    topic_decision = handlers._evaluate_message_access(topic_message, 99)
    non_topic_decision = handlers._evaluate_message_access(non_topic_message, 99)

    assert topic_decision.allowed is True
    assert non_topic_decision.allowed is False


# --- Typing lifecycle tests ---


def _make_bot_for_typing(*, typing_indicator: bool = True, typing_interval: int = 1):
    """Build a TelegramBot with mocked internals for typing tests."""
    config = TelegramConfig(
        enabled=True,
        bot_token="fake-token",
        typing_indicator=typing_indicator,
        typing_interval_seconds=typing_interval,
    )
    mock_app = MagicMock()
    mock_app.bot = MagicMock()
    mock_app.bot.send_chat_action = AsyncMock()
    mock_app.bot.send_message = AsyncMock()

    with (
        patch("amcp.telegram.bot.ApplicationBuilder") as builder_cls,
        patch("amcp.telegram.bot.CommandHandler", MagicMock()),
        patch("amcp.telegram.bot.MessageHandler", MagicMock()),
        patch("amcp.telegram.bot.filters", MagicMock()),
    ):
        builder_cls.return_value.token.return_value.build.return_value = mock_app

        from amcp.telegram.bot import TelegramBot

        bot = TelegramBot(
            token="fake-token",
            allowed_users={1},
            admin_users={1},
            config=config,
        )
    return bot


def test_typing_start_creates_task():
    async def _run():
        bot = _make_bot_for_typing()
        await bot._start_typing(100)

        assert 100 in bot._typing_tasks
        task = bot._typing_tasks[100]
        assert not task.done()

        await bot._stop_typing(100)
        assert 100 not in bot._typing_tasks

    asyncio.run(_run())


def test_typing_start_sends_immediate_chat_action():
    async def _run():
        bot = _make_bot_for_typing()

        await bot._start_typing(150)

        bot._application.bot.send_chat_action.assert_any_call(chat_id=150, action="typing")
        await bot._stop_typing(150)

    asyncio.run(_run())


def test_typing_stop_cancels_task():
    async def _run():
        bot = _make_bot_for_typing()
        await bot._start_typing(200)
        task = bot._typing_tasks[200]

        await bot._stop_typing(200)

        assert 200 not in bot._typing_tasks
        assert task.cancelled() or task.done()

    asyncio.run(_run())


def test_typing_disabled_skips():
    async def _run():
        bot = _make_bot_for_typing(typing_indicator=False)
        await bot._start_typing(300)

        assert 300 not in bot._typing_tasks

    asyncio.run(_run())


def test_typing_loop_sends_chat_action():
    async def _run():
        bot = _make_bot_for_typing(typing_interval=1)
        await bot._start_typing(400)

        # Let the loop fire at least once
        await asyncio.sleep(0.05)

        bot._application.bot.send_chat_action.assert_called_with(chat_id=400, action="typing")

        await bot._stop_typing(400)

    asyncio.run(_run())


def test_typing_stop_all():
    async def _run():
        bot = _make_bot_for_typing()
        await bot._start_typing(501)
        await bot._start_typing(502)
        assert len(bot._typing_tasks) == 2

        await bot._stop_all_typing()

        assert len(bot._typing_tasks) == 0

    asyncio.run(_run())


def test_process_message_starts_and_stops_typing():
    async def _run():
        bot = _make_bot_for_typing()

        class _MockAgent:
            session_id = "test"

            async def run(self, **kwargs):
                return "ok"

        session = SimpleNamespace(
            session_id="test",
            agent=_MockAgent(),
            lock=asyncio.Lock(),
            queue=__import__("collections").deque(),
            current_task=None,
        )
        msg = TelegramQueuedMessage(chat_id=600, user_id=1, text="hi")

        with (
            patch.object(bot, "_start_typing", new_callable=AsyncMock) as start,
            patch.object(bot, "_stop_typing", new_callable=AsyncMock) as stop,
        ):
            await bot._process_message(session, msg)

        start.assert_called_once_with(600)
        stop.assert_called_once_with(600)

    asyncio.run(_run())


def test_process_message_stops_typing_after_response_delivery():
    async def _run():
        bot = _make_bot_for_typing()
        events: list[str] = []

        class _MockAgent:
            session_id = "test"

            async def run(self, **kwargs):
                return "ok"

        session = SimpleNamespace(
            session_id="test",
            agent=_MockAgent(),
            lock=asyncio.Lock(),
            queue=__import__("collections").deque(),
            current_task=None,
        )
        msg = TelegramQueuedMessage(chat_id=650, user_id=1, text="hi")

        async def _start(chat_id: int) -> None:
            events.append(f"start:{chat_id}")

        async def _stop(chat_id: int) -> None:
            events.append(f"stop:{chat_id}")

        async def _send_markdown(chat_id: int, text: str) -> None:
            events.append(f"send:{chat_id}:{text}")

        with (
            patch.object(bot, "_start_typing", side_effect=_start),
            patch.object(bot, "_stop_typing", side_effect=_stop),
            patch.object(bot, "send_markdown", side_effect=_send_markdown),
        ):
            await bot._process_message(session, msg)

        assert events == ["start:650", "send:650:ok", "stop:650"]

    asyncio.run(_run())


def test_process_message_stops_typing_on_error():
    async def _run():
        bot = _make_bot_for_typing()

        class _ErrorAgent:
            session_id = "test"

            async def run(self, **kwargs):
                raise RuntimeError("boom")

        session = SimpleNamespace(
            session_id="test",
            agent=_ErrorAgent(),
            lock=asyncio.Lock(),
            queue=__import__("collections").deque(),
            current_task=None,
        )
        msg = TelegramQueuedMessage(chat_id=700, user_id=1, text="hi")

        with (
            patch.object(bot, "_start_typing", new_callable=AsyncMock) as start,
            patch.object(bot, "_stop_typing", new_callable=AsyncMock) as stop,
        ):
            await bot._process_message(session, msg)

        start.assert_called_once_with(700)
        stop.assert_called_once_with(700)

    asyncio.run(_run())
