import asyncio
import json
import re
import threading
import time
from unittest.mock import patch

import pytest

from ankaloop import tools as tools_module
from ankaloop.config import AnkaloopConfig, ChatConfig
from ankaloop.tools import (
    BashTool,
    GrepTool,
    ReadFileTool,
    ThinkTool,
    TodoTool,
    WebFetchTool,
    WebSearchTool,
    get_tool_registry,
)


def test_read_file_tool(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")

    tool = ReadFileTool()
    result = tool.execute(path=str(test_file))
    assert result.success
    assert "hello world" in result.content


def test_bash_tool_simple():
    tool = BashTool()
    result = tool.execute(command="echo test")
    assert result.success
    assert "test" in result.content


def test_bash_tool_uses_cwd(tmp_path):
    tool = BashTool()
    result = tool.execute(command="pwd", cwd=str(tmp_path))

    assert result.success
    assert str(tmp_path) in result.content
    assert result.metadata["cwd"] == str(tmp_path)


def test_bash_tool_truncates_large_output():
    tool = BashTool()
    result = tool.execute(command="printf '%*s' 7000 '' | tr ' ' x")

    assert result.success
    assert len(result.content) <= tool.MAX_OUTPUT_CHARS
    assert "...[truncated]" in result.content
    assert result.metadata["truncated"] is True
    assert result.metadata["original_output_length"] > tool.MAX_OUTPUT_CHARS


def test_think_tool():
    tool = ThinkTool()
    result = tool.execute(thought="test reasoning")
    assert result.success
    assert "test reasoning" in result.content


def test_grep_repairs_singular_path_without_changing_its_public_api():
    tool = GrepTool()

    assert tool.prepare_model_arguments({"pattern": "x", "path": "src"}) == {
        "pattern": "x",
        "paths": ["src"],
    }
    assert tool.prepare_model_arguments({"pattern": "x", "path": "alias", "paths": ["canonical"]}) == {
        "pattern": "x",
        "paths": ["canonical"],
    }
    assert tool.prepare_model_arguments({"pattern": "x", "path": None}) == {
        "pattern": "x",
        "path": None,
    }


def test_registry_reports_unbindable_arguments_without_raw_typeerror():
    result = get_tool_registry().execute_tool("grep", pattern="x", path="src")

    assert not result.success
    assert result.error is not None
    assert result.error.startswith("Invalid arguments:")
    assert "Did you mean 'paths'?" in result.error
    assert "TypeError" not in result.error


def test_edit_tool_enabled_controls_apply_patch_registry():
    cfg = AnkaloopConfig(
        servers={},
        chat=ChatConfig(write_tool_enabled=True, edit_tool_enabled=False),
    )
    with (
        patch.object(tools_module, "_default_registry", None),
        patch("ankaloop.config.load_config", return_value=cfg),
    ):
        registry = get_tool_registry()

    assert "write_file" in registry.list_tools()
    assert "apply_patch" not in registry.list_tools()


def test_web_search_tool_firecrawl_backend():
    tool = WebSearchTool()
    response = {
        "data": {
            "web": [
                {
                    "title": "Firecrawl Docs",
                    "url": "https://docs.firecrawl.dev",
                    "description": "Developer documentation",
                    "markdown": "Firecrawl can search and scrape the web.",
                }
            ]
        }
    }

    with patch("ankaloop.tools._firecrawl_search", return_value=response):
        result = tool.execute(query="firecrawl docs", backend="firecrawl", fetch_content=True)

    assert result.success
    assert "Firecrawl Docs" in result.content
    assert "https://docs.firecrawl.dev" in result.content


def test_web_tool_specs_hide_provider_details():
    specs = [WebSearchTool().get_spec(), WebFetchTool().get_spec()]

    for spec in specs:
        visible = json.dumps(spec).lower()
        assert "backend" not in visible
        assert "firecrawl" not in visible
        assert "preferred backend" not in visible
        assert re.search(r"\bexa\b", visible) is None


def test_internal_web_provider_defaults_do_not_require_config(monkeypatch):
    from ankaloop import config as config_module
    from ankaloop import tools

    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("ANKA_FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("FIRECRAWL_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda: config_module.AnkaloopConfig(servers={}, chat=None),
    )

    assert tools._get_exa_server_config().url == "https://mcp.exa.ai/mcp"
    assert tools._get_firecrawl_server_config().url == "https://mcp.firecrawl.dev/v2/mcp"


def test_firecrawl_search_uses_mcp_when_no_api_key(monkeypatch):
    """Without an API key, the keyless MCP free tier is used (no REST call)."""
    from ankaloop import tools
    from ankaloop.config import Server

    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("ANKA_FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("FIRECRAWL_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(tools, "_get_firecrawl_server_config", lambda: Server(url="https://mcp.firecrawl.dev/v2/mcp"))

    mcp_response = {
        "data": {"web": [{"title": "Rust Async", "url": "https://rust-lang.org/async", "description": "async await"}]}
    }
    with (
        patch("ankaloop.tools._call_firecrawl_mcp", return_value=mcp_response) as mcp_call,
        patch("ankaloop.tools._call_firecrawl") as rest_call,
    ):
        result = tools._firecrawl_search({"query": "rust async", "limit": 3})

    assert result == mcp_response
    mcp_call.assert_called_once()
    rest_call.assert_not_called()
    # Confirm the keyless tool name and passthrough args.
    assert mcp_call.call_args.args[0] == "firecrawl_search"
    assert mcp_call.call_args.args[1]["query"] == "rust async"


def test_firecrawl_search_uses_rest_when_api_key_set(monkeypatch):
    """With an API key set, the REST API is used (higher rate limits, full tools)."""
    from ankaloop import tools
    from ankaloop.config import Server

    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
    monkeypatch.setattr(tools, "_get_firecrawl_server_config", lambda: Server(url="https://mcp.firecrawl.dev/v2/mcp"))

    rest_response = {"data": {"web": []}}
    with (
        patch("ankaloop.tools._call_firecrawl", return_value=rest_response) as rest_call,
        patch("ankaloop.tools._call_firecrawl_mcp") as mcp_call,
    ):
        result = tools._firecrawl_search({"query": "rust async", "limit": 3})

    assert result == rest_response
    rest_call.assert_called_once()
    mcp_call.assert_not_called()


def test_web_search_tool_firecrawl_mcp_keyless(monkeypatch):
    """End-to-end: firecrawl backend routes through MCP when no API key is set."""
    from ankaloop import tools
    from ankaloop.config import Server

    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("ANKA_FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("FIRECRAWL_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(tools, "_get_firecrawl_server_config", lambda: Server(url="https://mcp.firecrawl.dev/v2/mcp"))

    mcp_response = {
        "data": {"web": [{"title": "Python Docs", "url": "https://docs.python.org", "description": "Python"}]}
    }
    tool = WebSearchTool()
    with (
        patch("ankaloop.tools._call_exa_tool", side_effect=Exception("exa unavailable")),
        patch("ankaloop.tools._call_firecrawl_mcp", return_value=mcp_response) as mcp_call,
        patch("ankaloop.tools._call_firecrawl") as rest_call,
    ):
        result = tool.execute(query="python docs", backend="auto")

    assert result.success
    assert "Python Docs" in result.content
    mcp_call.assert_called_once()
    rest_call.assert_not_called()


def test_web_fetch_tool_firecrawl_mcp_keyless(monkeypatch):
    """web_fetch firecrawl fallback uses MCP keyless tier without an API key."""
    from ankaloop import tools
    from ankaloop.config import Server

    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("ANKA_FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("FIRECRAWL_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(tools, "_get_firecrawl_server_config", lambda: Server(url="https://mcp.firecrawl.dev/v2/mcp"))

    mcp_response = {
        "data": {
            "markdown": "# Example\n\nThis is the fetched page content.",
            "metadata": {"title": "Example Page"},
        }
    }
    tool = WebFetchTool()
    with (
        patch("ankaloop.tools._call_exa_tool", side_effect=Exception("exa unavailable")),
        patch("ankaloop.tools._call_firecrawl_mcp", return_value=mcp_response) as mcp_call,
        patch("ankaloop.tools._call_firecrawl") as rest_call,
    ):
        result = tool.execute(url="https://example.com", backend="auto")

    assert result.success
    assert "Example Page" in result.content
    assert "fetched page content" in result.content
    mcp_call.assert_called_once()
    rest_call.assert_not_called()


def test_web_fetch_tool_auto_prefers_exa():
    tool = WebFetchTool()
    exa_response = {
        "content": [
            {
                "type": "text",
                "text": "Example Domain\nhttps://example.com\nThis domain is for use in examples.",
            }
        ]
    }

    with (
        patch("ankaloop.tools._call_exa_tool", return_value=exa_response),
        patch("ankaloop.tools._call_firecrawl") as firecrawl_call,
    ):
        result = tool.execute(url="https://example.com", backend="auto")

    assert result.success
    assert "Example Domain" in result.content
    firecrawl_call.assert_not_called()


class TestTodoTool:
    """Tests for TodoTool."""

    def test_read_empty(self):
        """Test reading empty todo list."""
        tool = TodoTool()
        result = tool.execute(action="read", _session_id="test")
        assert result.success
        assert "No todos" in result.content

    def test_write_and_read(self):
        """Test writing and reading todos."""
        tool = TodoTool()
        todos = [
            {"id": "1", "content": "First task", "status": "pending"},
            {"id": "2", "content": "Second task", "status": "in_progress"},
        ]
        result = tool.execute(action="write", todos=todos, _session_id="test")
        assert result.success

        result = tool.execute(action="read", _session_id="test")
        assert "First task" in result.content
        assert "Second task" in result.content

    def test_status_icons(self):
        """Test todos display correct status icons."""
        tool = TodoTool()
        todos = [
            {"id": "1", "content": "Pending", "status": "pending"},
            {"id": "2", "content": "Progress", "status": "in_progress"},
            {"id": "3", "content": "Done", "status": "completed"},
            {"id": "4", "content": "Cancelled", "status": "cancelled"},
        ]
        tool.execute(action="write", todos=todos, _session_id="test")
        result = tool.execute(action="read", _session_id="test")
        assert "⬜" in result.content
        assert "🔄" in result.content
        assert "✅" in result.content
        assert "❌" in result.content

    def test_invalid_action(self):
        """Test invalid action."""
        tool = TodoTool()
        result = tool.execute(action="invalid", _session_id="test")
        assert not result.success

    def test_duplicate_ids_rejected(self):
        """Test duplicate IDs are rejected."""
        tool = TodoTool()
        todos = [{"id": "1", "content": "A"}, {"id": "1", "content": "B"}]
        result = tool.execute(action="write", todos=todos, _session_id="test")
        assert not result.success

    def test_registered_in_registry(self):
        """Test todo tool is in default registry."""
        registry = get_tool_registry()
        assert "todo" in registry.list_tools()
        assert "web_search" in registry.list_tools()
        assert "web_fetch" in registry.list_tools()


class TestRunCoroutineInThread:
    """_run_coroutine_in_thread must never block the caller forever."""

    def test_returns_result(self):
        from ankaloop.tools import _run_coroutine_in_thread

        async def coro():
            return 42

        assert _run_coroutine_in_thread(coro()) == 42

    def test_propagates_exception(self):
        from ankaloop.tools import _run_coroutine_in_thread

        async def coro():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            _run_coroutine_in_thread(coro())

    def test_join_timeout_raises_and_unblocks(self):
        from ankaloop.tools import ToolExecutionError, _run_coroutine_in_thread

        started = threading.Event()

        async def hung():
            started.set()
            await asyncio.sleep(60)

        begin = time.monotonic()
        with pytest.raises(ToolExecutionError, match="timed out"):
            _run_coroutine_in_thread(hung(), timeout=0.2)
        elapsed = time.monotonic() - begin
        assert elapsed < 5, "join timeout should unblock the caller quickly"
        assert started.is_set(), "worker coroutine should have started before timing out"
