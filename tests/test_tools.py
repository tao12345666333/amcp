from unittest.mock import patch

from amcp.tools import BashTool, ReadFileTool, ThinkTool, TodoTool, WebFetchTool, WebSearchTool, get_tool_registry


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

    with patch("amcp.tools._call_firecrawl", return_value=response):
        result = tool.execute(query="firecrawl docs", backend="firecrawl", fetch_content=True)

    assert result.success
    assert "Firecrawl Docs" in result.content
    assert "https://docs.firecrawl.dev" in result.content


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
        patch("amcp.tools._call_exa_tool", return_value=exa_response),
        patch("amcp.tools._call_firecrawl") as firecrawl_call,
    ):
        result = tool.execute(url="https://example.com", backend="auto")

    assert result.success
    assert "Example Domain" in result.content
    firecrawl_call.assert_not_called()


class TestTodoTool:
    """Tests for TodoTool."""

    def setup_method(self):
        """Reset todos before each test."""
        TodoTool._todos = []

    def test_read_empty(self):
        """Test reading empty todo list."""
        tool = TodoTool()
        result = tool.execute(action="read")
        assert result.success
        assert "No todos" in result.content

    def test_write_and_read(self):
        """Test writing and reading todos."""
        tool = TodoTool()
        todos = [
            {"id": "1", "content": "First task", "status": "pending"},
            {"id": "2", "content": "Second task", "status": "in_progress"},
        ]
        result = tool.execute(action="write", todos=todos)
        assert result.success

        result = tool.execute(action="read")
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
        tool.execute(action="write", todos=todos)
        result = tool.execute(action="read")
        assert "⬜" in result.content
        assert "🔄" in result.content
        assert "✅" in result.content
        assert "❌" in result.content

    def test_invalid_action(self):
        """Test invalid action."""
        tool = TodoTool()
        result = tool.execute(action="invalid")
        assert not result.success

    def test_duplicate_ids_rejected(self):
        """Test duplicate IDs are rejected."""
        tool = TodoTool()
        todos = [{"id": "1", "content": "A"}, {"id": "1", "content": "B"}]
        result = tool.execute(action="write", todos=todos)
        assert not result.success

    def test_registered_in_registry(self):
        """Test todo tool is in default registry."""
        registry = get_tool_registry()
        assert "todo" in registry.list_tools()
        assert "web_search" in registry.list_tools()
        assert "web_fetch" in registry.list_tools()
