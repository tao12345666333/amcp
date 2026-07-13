"""Tests for the built-in telegram-sender skill script."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "amcp"
    / "builtin_skills"
    / "telegram-sender"
    / "scripts"
    / "telegram_send.py"
)


@pytest.fixture
def telegram_send_script(monkeypatch):
    """Load telegram_send.py with lightweight optional dependency stubs."""
    requests_stub = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "requests", requests_stub)

    spec = importlib.util.spec_from_file_location("telegram_send_skill_script", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    """Minimal response object for script request calls."""

    def __init__(self, payload: dict | None = None, chunks: list[bytes] | None = None):
        self._payload = payload or {"ok": True, "result": {"message_id": 123}}
        self._chunks = chunks or []
        self.headers = {"content-type": "image/png"}

    def raise_for_status(self) -> None:
        """Pretend the request succeeded."""

    def json(self) -> dict:
        """Return the fake Telegram payload."""
        return self._payload

    def iter_content(self, chunk_size: int):
        """Yield fake download chunks."""
        yield from self._chunks


def test_to_markdownv2_converts_standard_markdown(telegram_send_script):
    """The skill should render standard Markdown as Telegram MarkdownV2."""
    converted = telegram_send_script._to_markdownv2("**bold** and [link](https://example.com)")

    assert converted == "*bold* and [link](https://example.com)"


def test_send_photo_file_id_uses_json_payload(telegram_send_script):
    """Telegram file_id sources should be sent directly without multipart upload."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    telegram_send_script.requests = types.SimpleNamespace(post=fake_post)

    result = telegram_send_script.send_photo(
        "token",
        "chat-1",
        "AgACAgUAAxkBAAIB_LONG_FILE_ID_FOR_REUSE_WITH_BOT",
        caption="hello",
        reply_to_message_id=42,
    )

    assert result["ok"] is True
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://api.telegram.org/bottoken/sendPhoto"
    assert kwargs["json"] == {
        "chat_id": "chat-1",
        "caption": "hello",
        "parse_mode": "MarkdownV2",
        "reply_to_message_id": 42,
        "photo": "AgACAgUAAxkBAAIB_LONG_FILE_ID_FOR_REUSE_WITH_BOT",
    }
    assert "files" not in kwargs


def test_send_photo_local_path_uses_multipart_upload(telegram_send_script, tmp_path):
    """Local photo paths should be uploaded as multipart/form-data."""
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"png data")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    telegram_send_script.requests = types.SimpleNamespace(post=fake_post)

    telegram_send_script.send_photo("token", "chat-1", str(image_path), caption="caption")

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://api.telegram.org/bottoken/sendPhoto"
    assert kwargs["data"] == {
        "chat_id": "chat-1",
        "caption": "caption",
        "parse_mode": "MarkdownV2",
    }
    assert kwargs["files"]["photo"][0] == "image.png"
    assert "json" not in kwargs


def test_send_photo_url_downloads_then_uploads_and_cleans_temp(telegram_send_script):
    """HTTP(S) photos should be downloaded first, uploaded, then removed."""
    uploaded_paths: list[Path] = []

    def fake_get(url, **kwargs):
        assert url == "https://cdn.example.com/photo"
        assert kwargs == {"stream": True, "timeout": 60}
        return FakeResponse(chunks=[b"chunk-1", b"chunk-2"])

    def fake_post(url, **kwargs):
        assert url == "https://api.telegram.org/bottoken/sendPhoto"
        upload_file = kwargs["files"]["photo"][1]
        uploaded_path = Path(upload_file.name)
        uploaded_paths.append(uploaded_path)
        assert uploaded_path.suffix == ".png"
        assert uploaded_path.read_bytes() == b"chunk-1chunk-2"
        return FakeResponse()

    telegram_send_script.requests = types.SimpleNamespace(get=fake_get, post=fake_post)

    telegram_send_script.send_photo("token", "chat-1", "https://cdn.example.com/photo")

    assert len(uploaded_paths) == 1
    assert not uploaded_paths[0].exists()
