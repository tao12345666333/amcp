"""Tests for shared chat client helpers."""

from unittest.mock import MagicMock, patch

from amcp.chat import _make_client, _resolve_api_key, _resolve_base_url


class TestResolveBaseUrl:
    def test_cli_overrides_all(self):
        assert _resolve_base_url("https://cli.com/v1", None) == "https://cli.com/v1"

    def test_config_used_when_no_cli(self):
        cfg = MagicMock()
        cfg.base_url = "https://cfg.com"
        assert _resolve_base_url(None, cfg) == "https://cfg.com"

    def test_env_used_when_no_config(self, monkeypatch):
        monkeypatch.setenv("AMCP_OPENAI_BASE", "https://env.com")
        assert _resolve_base_url(None, None) == "https://env.com"

    def test_default_fallback(self, monkeypatch):
        monkeypatch.delenv("AMCP_OPENAI_BASE", raising=False)
        assert _resolve_base_url(None, None) == "https://api.gmi-serving.com/v1"

    def test_preserves_provider_specific_path(self):
        base_url = "https://api-gateway.example.com/v1/openai"
        assert _resolve_base_url(base_url, None) == base_url


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
        with patch("amcp.chat.AnyLLMClient") as client_cls:
            _make_client(
                base_url="https://api.example.com/v1",
                api_key="test-key",
                provider="gmi",
                model="test-model",
            )
            client_cls.assert_called_once_with(
                provider="gmi",
                base_url="https://api.example.com/v1",
                api_key="test-key",
                model="test-model",
            )
