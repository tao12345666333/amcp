"""Rich Live UI for tool execution display."""

from __future__ import annotations

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

console = Console()

# Max lines to show in result preview
MAX_PREVIEW_LINES = 8


def _extract_key_arg(tool_name: str, args: dict) -> str | None:
    """Extract the most relevant argument for display."""
    key_args = {
        "read_file": "path",
        "grep": "pattern",
        "bash": "command",
        "write_file": "path",
        "edit_file": "path",
    }
    key = key_args.get(tool_name)
    if key and key in args:
        val = str(args[key])
        return val[:80] + "..." if len(val) > 80 else val
    # For MCP tools, try common arg names
    for k in ("query", "url", "path", "command"):
        if k in args:
            val = str(args[k])
            return val[:80] + "..." if len(val) > 80 else val
    return None


def _format_preview(content: str) -> str:
    """Format content preview."""
    lines = content.strip().split("\n")

    if len(lines) <= MAX_PREVIEW_LINES:
        return content.strip()

    preview_lines = lines[:MAX_PREVIEW_LINES]
    remaining = len(lines) - MAX_PREVIEW_LINES
    preview_lines.append(f"... ({remaining} more lines)")
    return "\n".join(preview_lines)


class ToolBlock:
    """Represents a single tool call display block."""

    def __init__(self, tool_name: str, args: dict):
        self.tool_name = tool_name
        self.args = args
        self.key_arg = _extract_key_arg(tool_name, args)
        self.finished = False
        self.success = True
        self.result_preview: str | None = None
        self._spinner = Spinner("dots")

    def finish(self, success: bool = True, result: str | None = None):
        self.finished = True
        self.success = success
        if result:
            self.result_preview = _format_preview(result)

    def render(self) -> RenderableType:
        # Special handling for think tool
        if self.tool_name == "think":
            return self._render_think()

        # Build headline
        if self.finished:
            icon = "[green]✓[/green]" if self.success else "[red]✗[/red]"
            verb = "Used"
        else:
            icon = "⋯"
            verb = "Using"

        arg_part = f" [dim]({self.key_arg})[/dim]" if self.key_arg else ""
        headline = Text.from_markup(f"{icon} {verb} [blue]{self.tool_name}[/blue]{arg_part}")

        if not self.finished:
            return Group(self._spinner, headline)

        # Show result preview in a compact panel
        if self.result_preview:
            border_style = "green" if self.success else "red"
            result_panel = Panel(
                self.result_preview,
                border_style=border_style,
                padding=(0, 1),
            )
            return Group(headline, result_panel)

        return headline

    def _render_think(self) -> RenderableType:
        """Render think tool with special styling."""
        if not self.finished:
            return Group(self._spinner, Text("🤔 Thinking...", style="italic dim"))

        # Extract thought content
        thought = self.args.get("thought", "")
        if self.result_preview and "Thinking:" in self.result_preview:
            thought = self.result_preview.split("Thinking:", 1)[-1].strip()

        # Show thought in italic gray style
        return Panel(
            Text(thought, style="italic"),
            title="[dim]💭 Thinking[/dim]",
            border_style="dim",
            padding=(0, 1),
        )


class LiveUI:
    """Manages live display of tool executions."""

    def __init__(self):
        self.tool_blocks: list[ToolBlock] = []
        self._live: Live | None = None

    def __enter__(self):
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=10,
            transient=True,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args):
        if self._live:
            self._live.__exit__(*args)
            # Print final state
            for block in self.tool_blocks:
                console.print(block.render())
            self._live = None

    def _render(self) -> RenderableType:
        if not self.tool_blocks:
            return Text("")
        return Group(*[b.render() for b in self.tool_blocks])

    def refresh(self):
        if self._live:
            self._live.update(self._render())

    def add_tool(self, tool_name: str, args: dict) -> ToolBlock:
        block = ToolBlock(tool_name, args)
        self.tool_blocks.append(block)
        self.refresh()
        return block

    def finish_tool(self, block: ToolBlock, success: bool = True, result: str | None = None):
        block.finish(success, result)
        self.refresh()

    def clear(self):
        self.tool_blocks = []
        self.refresh()
