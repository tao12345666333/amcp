from amcp.tools import BashTool, ReadFileTool, ThinkTool


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
