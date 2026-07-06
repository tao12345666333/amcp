"""Tests for chat module utilities."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from amcp.chat import (
    _attach_file_context,
    _builtin_read_tool_spec,
    _dispatch_tool_call,
    _get_chat_runtime_settings,
    _is_within_root,
    _make_client,
    _normalize_exa_web_search_args,
    _parse_read_intent,
    _resolve_api_key,
    _resolve_base_url,
)


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
        assert _resolve_base_url(None, None) == "https://inference.baseten.co/v1"

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


class TestParseReadIntent:
    def test_read_cmd_whole_file(self):
        result = _parse_read_intent("/read src/main.py")
        assert len(result) == 1
        assert result[0][0] == Path("src/main.py")
        assert result[0][1] is None

    def test_read_cmd_with_range(self):
        result = _parse_read_intent("read src/main.py lines 10-20")
        assert len(result) == 1
        assert result[0][0] == Path("src/main.py")
        assert result[0][1] == ["10-20"]

    def test_inline_path_range(self):
        result = _parse_read_intent("src/main.py:10-20")
        assert len(result) == 1
        assert result[0][0] == Path("src/main.py")
        assert result[0][1] == ["10-20"]

    def test_no_match(self):
        result = _parse_read_intent("hello world")
        assert result == []


class TestIsWithinRoot:
    def test_inside_root(self):
        assert _is_within_root(Path("/a/b/c"), Path("/a")) is True

    def test_outside_root(self):
        assert _is_within_root(Path("/x/y"), Path("/a")) is False

    def test_same_as_root(self):
        assert _is_within_root(Path("/a"), Path("/a")) is True


class TestDispatchToolCall:
    def test_unknown_tool(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            _dispatch_tool_call("unknown", {}, settings={"allowed_roots": [Path.cwd()], "default_max_lines": 400})

    def test_file_not_found(self, tmp_path):
        settings = {"allowed_roots": [tmp_path], "default_max_lines": 400}
        with pytest.raises(FileNotFoundError):
            _dispatch_tool_call("read_file", {"path": str(tmp_path / "missing.txt")}, settings=settings)

    def test_directory_not_allowed(self, tmp_path):
        settings = {"allowed_roots": [tmp_path], "default_max_lines": 400}
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        with pytest.raises(ValueError, match="directory"):
            _dispatch_tool_call("read_file", {"path": str(subdir)}, settings=settings)

    def test_path_outside_roots(self, tmp_path):
        settings = {"allowed_roots": [tmp_path], "default_max_lines": 400}
        with pytest.raises(ValueError, match="outside allowed"):
            _dispatch_tool_call("read_file", {"path": "/etc/passwd"}, settings=settings)

    def test_successful_read(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        settings = {"allowed_roots": [tmp_path], "default_max_lines": 400}
        tool_text, rendered = _dispatch_tool_call("read_file", {"path": str(test_file)}, settings=settings)
        assert "READ_FILE OK" in tool_text
        assert "hello world" in tool_text


class TestBuiltinReadToolSpec:
    def test_has_expected_fields(self):
        spec = _builtin_read_tool_spec()
        assert spec["type"] == "function"
        fn = spec["function"]
        assert fn["name"] == "read_file"
        assert "path" in fn["parameters"]["properties"]
        assert "ranges" in fn["parameters"]["properties"]
        assert "max_lines" in fn["parameters"]["properties"]


class TestGetChatRuntimeSettings:
    def test_defaults(self):
        with patch("amcp.chat.load_config") as mock_load:
            mock_cfg = MagicMock()
            mock_cfg.chat = None
            mock_load.return_value = mock_cfg
            settings = _get_chat_runtime_settings()
            assert settings["tool_loop_limit"] == 5
            assert settings["default_max_lines"] == 400

    def test_override(self):
        with patch("amcp.chat.load_config") as mock_load:
            mock_cfg = MagicMock()
            mock_cfg.chat = None
            mock_load.return_value = mock_cfg
            settings = _get_chat_runtime_settings({"tool_loop_limit": 10, "default_max_lines": 200})
            assert settings["tool_loop_limit"] == 10
            assert settings["default_max_lines"] == 200


class TestNormalizeExaWebSearchArgs:
    def test_query_synonyms(self):
        assert _normalize_exa_web_search_args({"q": "test"})["query"] == "test"
        assert _normalize_exa_web_search_args({"query_text": "test"})["query"] == "test"

    def test_num_results_synonyms(self):
        assert _normalize_exa_web_search_args({"query": "x", "num_results": 10})["numResults"] == 10
        assert _normalize_exa_web_search_args({"query": "x", "limit": 5})["numResults"] == 5

    def test_default_type(self):
        assert _normalize_exa_web_search_args({"query": "x"})["type"] == "fast"

    def test_preserves_existing(self):
        args = {"query": "x", "numResults": 8, "type": "neural"}
        assert _normalize_exa_web_search_args(args) == {"query": "x", "numResults": 8, "type": "neural"}


class TestAttachFileContext:
    def test_reads_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3")
        rendered, llm = _attach_file_context(test_file, None, max_lines=400)
        assert "line1" in rendered
        assert "line1" in llm

    def test_truncates_when_no_ranges(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("\n".join(f"line{i}" for i in range(500)))
        rendered, llm = _attach_file_context(test_file, None, max_lines=10)
        assert "[...truncated...]" in rendered

    def test_respects_ranges(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("\n".join(f"line{i}" for i in range(100)))
        rendered, llm = _attach_file_context(test_file, ["5-10"], max_lines=400)
        assert "line5" in llm
        assert "line9" in llm


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
