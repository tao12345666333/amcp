from io import StringIO

from rich.console import Console

from amcp.ui import ToolBlock


def test_tool_block_renders_markup_like_dynamic_text_safely():
    block = ToolBlock("web_search", {"query": "e2b supports [/llms.txt] persistence"})
    block.finish(success=False, result="closing tag '[/llms.txt]' at position 48")

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    console.print(block.render())

    output = buffer.getvalue()
    assert "[/llms.txt]" in output
    assert "web_search" in output
