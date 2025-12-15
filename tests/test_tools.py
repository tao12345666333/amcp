from amcp.tools import BashTool, ReadFileTool, ThinkTool, TodoTool, get_tool_registry


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


def test_think_tool():
    tool = ThinkTool()
    result = tool.execute(thought="test reasoning")
    assert result.success
    assert "test reasoning" in result.content


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
