from amcp.telegram.auth import AuthMiddleware
from amcp.telegram.formatter import TelegramFormatter
from amcp.telegram.handlers import SessionManager


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
