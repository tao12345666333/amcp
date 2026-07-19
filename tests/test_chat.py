"""Tests for shared chat client helpers."""

from unittest.mock import MagicMock, patch

from amcp.chat import _make_client, _resolve_api_key, _resolve_base_url


class TestResolveBaseUrl:
    def test_cli_overrides_all(self):
        assert _resolve_base_url("https://cli.com/v1", None) == "https://cli.com/v1"

    def test_config_used_when_no_cli(self):
        cfg = MagicMock()
        cfg.base_url = "https://cfg.com"
        assert _resolve_base_url(None, cfg) == "https://cfg.com/v1"

    def test_env_used_when_no_config(self, monkeypatch):
        monkeypatch.setenv("AMCP_OPENAI_BASE", "https://env.com")
        assert _resolve_base_url(None, None) == "https://env.com/v1"

    def test_default_fallback(self, monkeypatch):
        monkeypatch.delenv("AMCP_OPENAI_BASE", raising=False)
        assert _resolve_base_url(None, None) == "https://api.gmi-serving.com/v1"

    def test_appends_v1_when_missing(self):
        assert _resolve_base_url("https://example.com", None) == "https://example.com/v1"


class TestResolveApiKey:
    def test_cli_overrides_all(self):
        assert _resolve_api_key("cli-key", None) == "cli-key"

    def test_config_used_when_no_cli(self):
        cfg = MagicMock()
        cfg.api_key = "cfg-key"
        assert _resolve_api_key(None, cfg) == "cfg-key"

    def test_none_when_missing(self):
        assert _resolve_api_key(None, None) is None


class TestMakeClient:
    def test_creates_client(self):
        with patch("builtins.__import__") as mock_import:
            mock_openai = MagicMock()
            mock_import.return_value = MagicMock(OpenAI=mock_openai)
            _make_client("https://api.example.com/v1", "test-key")
            mock_openai.assert_called_once_with(
                base_url="https://api.example.com/v1",
                api_key="test-key",
                default_headers={"User-Agent": "AMCPAgent"},
            )
