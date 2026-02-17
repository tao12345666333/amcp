import json
from types import SimpleNamespace

from amcp.telegram.auth import AuthMiddleware
from amcp.telegram.formatter import TelegramFormatter
from amcp.telegram.handlers import (
    SessionManager,
    _build_enriched_prompt,
    _exclude_none,
    _extract_reply_metadata,
)


class _FakeAgent:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


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


# --- Metadata injection tests ---


def test_exclude_none_removes_none():
    result = _exclude_none({"a": 1, "b": None, "c": "hello", "d": None})
    assert result == {"a": 1, "c": "hello"}


def test_exclude_none_keeps_falsy():
    result = _exclude_none({"a": 0, "b": "", "c": False, "d": None})
    assert result == {"a": 0, "b": "", "c": False}


def _make_message(text="hello", chat_id=123, message_id=10, reply_to=None):
    user = SimpleNamespace(
        id=42,
        username="tester",
        full_name="Test User",
        first_name="Test",
        last_name="User",
        is_bot=False,
    )
    chat = SimpleNamespace(type="private")
    return SimpleNamespace(
        chat_id=chat_id,
        chat=chat,
        message_id=message_id,
        text=text,
        from_user=user,
        reply_to_message=reply_to,
        date=None,
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
