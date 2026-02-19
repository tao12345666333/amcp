"""Tests for TelegramSendTool."""

from unittest.mock import MagicMock, patch

import pytest

from amcp.telegram.tools import TelegramSendTool
from amcp.tools import ToolResult


@pytest.fixture
def tool():
    return TelegramSendTool(bot_token="test-token-123")


class TestTelegramSendToolProperties:
    def test_name(self, tool):
        assert tool.name == "telegram_send"

    def test_description(self, tool):
        assert "send" in tool.description.lower()
        assert "edit" in tool.description.lower()
        assert "notify" in tool.description.lower()

    def test_get_spec(self, tool):
        spec = tool.get_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "telegram_send"
        params = spec["function"]["parameters"]
        assert "action" in params["properties"]
        assert "text" in params["properties"]
        assert params["required"] == ["action", "text"]

    def test_parameters_schema(self, tool):
        schema = tool.get_parameters_schema()
        assert schema["properties"]["action"]["enum"] == ["send", "edit", "notify"]
        assert schema["additionalProperties"] is False


class TestTelegramSendToolValidation:
    def test_no_token(self):
        tool = TelegramSendTool(bot_token="")
        result = tool.execute(action="send", text="hello", chat_id="123")
        assert not result.success
        assert "token" in result.error.lower()

    def test_invalid_action(self, tool):
        result = tool.execute(action="delete", text="hello")
        assert not result.success
        assert "Invalid action" in result.error

    def test_send_missing_chat_id(self, tool):
        result = tool.execute(action="send", text="hello")
        assert not result.success
        assert "chat_id" in result.error

    def test_edit_missing_chat_id(self, tool):
        result = tool.execute(action="edit", text="hello", message_id=42)
        assert not result.success
        assert "chat_id" in result.error

    def test_edit_missing_message_id(self, tool):
        result = tool.execute(action="edit", text="hello", chat_id="123")
        assert not result.success
        assert "message_id" in result.error


class TestTelegramSendAction:
    @patch("amcp.telegram.tools.httpx")
    def test_send_success(self, mock_httpx, tool):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 99},
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response

        result = tool.execute(action="send", text="Hello!", chat_id="12345")

        assert result.success
        assert "99" in result.content
        assert result.metadata["message_id"] == 99
        mock_httpx.post.assert_called_once()
        call_kwargs = mock_httpx.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["chat_id"] == "12345"
        assert payload["text"]  # text is present (possibly converted)

    @patch("amcp.telegram.tools.httpx")
    def test_send_with_reply(self, mock_httpx, tool):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 100},
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response

        result = tool.execute(
            action="send",
            text="Reply text",
            chat_id="123",
            reply_to_message_id=42,
        )

        assert result.success
        call_kwargs = mock_httpx.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["reply_to_message_id"] == 42

    @patch("amcp.telegram.tools.httpx")
    def test_send_http_error(self, mock_httpx, tool):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"description":"Bad Request"}'
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request",
            request=MagicMock(),
            response=mock_response,
        )
        mock_httpx.post.return_value = mock_response
        mock_httpx.HTTPStatusError = httpx.HTTPStatusError
        mock_httpx.HTTPError = httpx.HTTPError

        result = tool.execute(action="send", text="test", chat_id="123")

        assert not result.success
        assert "400" in result.error


class TestTelegramEditAction:
    @patch("amcp.telegram.tools.httpx")
    def test_edit_success(self, mock_httpx, tool):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 42},
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response

        result = tool.execute(
            action="edit",
            text="Updated text",
            chat_id="123",
            message_id=42,
        )

        assert result.success
        assert result.metadata["method"] == "editMessageText"
        call_kwargs = mock_httpx.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["message_id"] == 42


class TestTelegramNotifyAction:
    @patch("amcp.telegram.tools.httpx")
    def test_notify_success(self, mock_httpx, tool):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 1},
        }
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response

        mock_config = MagicMock()
        mock_config.telegram.allowed_users = [111, 222]

        with patch("amcp.telegram.tools.load_config", return_value=mock_config):
            result = tool.execute(action="notify", text="Deploy done")

        assert result.success
        assert "2 user(s)" in result.content
        assert mock_httpx.post.call_count == 2

    def test_notify_no_users(self, tool):
        mock_config = MagicMock()
        mock_config.telegram = None

        with patch("amcp.telegram.tools.load_config", return_value=mock_config):
            result = tool.execute(action="notify", text="test")

        assert not result.success
        assert "No allowed users" in result.error

    @patch("amcp.telegram.tools.httpx")
    def test_notify_partial_failure(self, mock_httpx, tool):
        import httpx

        success_response = MagicMock()
        success_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 1},
        }
        success_response.raise_for_status = MagicMock()

        error_response = MagicMock()
        error_response.status_code = 403
        error_response.text = "Forbidden"
        error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403",
            request=MagicMock(),
            response=error_response,
        )

        mock_httpx.post.side_effect = [success_response, error_response]
        mock_httpx.HTTPStatusError = httpx.HTTPStatusError
        mock_httpx.HTTPError = httpx.HTTPError

        mock_config = MagicMock()
        mock_config.telegram.allowed_users = [111, 222]

        with patch("amcp.telegram.tools.load_config", return_value=mock_config):
            result = tool.execute(action="notify", text="test")

        assert result.success  # partial success
        assert "1 failed" in result.content


class TestToolRegistration:
    def test_tool_registry_integration(self):
        from amcp.tools import ToolRegistry

        registry = ToolRegistry()
        tool = TelegramSendTool(bot_token="test")
        registry.register(tool)

        assert "telegram_send" in registry.list_tools()
        assert registry.get_tool("telegram_send") is tool

        registry.unregister("telegram_send")
        assert "telegram_send" not in registry.list_tools()
