from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from rich.console import Console


@dataclass
class ToolResult:
    """Result of tool execution."""

    success: bool
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ToolError(Exception):
    """Base exception for tool errors."""

    pass


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""

    pass


class ToolValidationError(ToolError):
    """Raised when tool parameters are invalid."""

    pass


@runtime_checkable
class Tool(Protocol):
    """Protocol for tool implementations."""

    @property
    def name(self) -> str:
        """Tool name."""
        ...

    @property
    def description(self) -> str:
        """Tool description."""
        ...

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given parameters."""
        ...

    def get_spec(self) -> dict[str, Any]:
        """Get tool specification for LLM."""
        ...


class BaseTool(ABC):
    """Base class for tool implementations."""

    def __init__(self):
        self.console = Console()

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters."""
        pass

    def validate_parameters(self, **kwargs) -> None:  # noqa: B027
        """Validate tool parameters. Override in subclasses."""
        pass

    def get_spec(self) -> dict[str, Any]:
        """Get tool specification for LLM."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema(),
            },
        }

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get JSON schema for tool parameters. Override in subclasses."""
        return {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._tool_specs: dict[str, dict[str, Any]] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self._tool_specs[tool.name] = tool.get_spec() if hasattr(tool, "get_spec") else {}

    def unregister(self, name: str) -> None:
        """Unregister a tool."""
        self._tools.pop(name, None)
        self._tool_specs.pop(name, None)

    def get_tool(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_tool_specs(self) -> dict[str, dict[str, Any]]:
        """Get all tool specifications."""
        return self._tool_specs.copy()

    def execute_tool(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name."""
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(success=False, content="", error=f"Tool '{name}' not found")

        try:
            # Validate parameters
            if hasattr(tool, "validate_parameters"):
                tool.validate_parameters(**kwargs)

            # Execute tool
            result = tool.execute(**kwargs)
            return result

        except Exception as e:
            return ToolResult(success=False, content="", error=f"Tool execution failed: {type(e).__name__}: {e}")


# Built-in tools
class ReadFileTool(BaseTool):
    """Tool for reading files with slice and indentation-aware modes.

    Supports two modes:
    - slice (default): Read specific line ranges
    - indentation: Intelligently expand around an anchor line based on code structure
    """

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return """Read a text file from the local workspace.

Modes:
- slice (default): Read specific line ranges. Use 'ranges' parameter.
- indentation: Intelligently read a code block around an anchor line.
  Automatically captures the surrounding context (function, class, etc.).
  Use 'offset', 'anchor_line', 'max_levels' parameters.

Use relative paths from current working directory."""

    def execute(  # type: ignore[override]
        self,
        path: str,
        # Slice mode parameters
        ranges: list[str] | None = None,
        max_lines: int | None = None,
        # Mode selection
        mode: str = "slice",
        # Indentation mode parameters
        offset: int = 1,
        limit: int = 200,
        anchor_line: int | None = None,
        max_levels: int = 2,
        include_siblings: bool = False,
        include_header: bool = True,
    ) -> ToolResult:
        """Execute the read file tool.

        Args:
            path: Path to file
            ranges: Line ranges for slice mode (e.g., ["1-100", "200-250"])
            max_lines: Maximum lines to return per block
            mode: "slice" or "indentation"
            offset: Starting line for indentation mode (1-indexed)
            limit: Max lines to return in indentation mode
            anchor_line: Center line for indentation expansion (defaults to offset)
            max_levels: How many parent indentation levels to include (0=unlimited)
            include_siblings: Include blocks at same indentation level
            include_header: Include comments/decorators above the block
        """
        from pathlib import Path

        try:
            file_path = Path(path).expanduser().resolve()

            if not file_path.exists():
                return ToolResult(success=False, content="", error=f"File not found: {file_path}")

            if not file_path.is_file():
                return ToolResult(success=False, content="", error=f"Path is a directory, not a file: {file_path}")

            if mode == "indentation":
                return self._read_indentation_mode(
                    file_path,
                    offset=offset,
                    limit=limit,
                    anchor_line=anchor_line,
                    max_levels=max_levels,
                    include_siblings=include_siblings,
                    include_header=include_header,
                    max_lines=max_lines,
                )
            else:
                return self._read_slice_mode(file_path, ranges, max_lines)

        except Exception as e:
            return ToolResult(success=False, content="", error=f"Failed to read file: {type(e).__name__}: {e}")

    def _read_slice_mode(self, file_path: Path, ranges: list[str] | None, max_lines: int | None) -> ToolResult:
        """Read file using slice mode (line ranges)."""
        from .readfile import read_file_with_ranges

        blocks = read_file_with_ranges(file_path, ranges or [])

        content_parts = []
        for block in blocks:
            header = f"{file_path}:{block['start']}-{block['end']}"
            content_parts.append(f"**{header}**")

            for lineno, line in block["lines"][: max_lines or 400]:
                content_parts.append(f"{lineno:>6} | {line}")

            if len(block["lines"]) > (max_lines or 400):
                content_parts.append("... (truncated)")

        content = "\n".join(content_parts)

        return ToolResult(
            success=True,
            content=content,
            metadata={
                "file_path": str(file_path),
                "mode": "slice",
                "blocks_read": len(blocks),
                "total_lines": sum(len(block["lines"]) for block in blocks),
            },
        )

    def _read_indentation_mode(
        self,
        file_path: Path,
        offset: int,
        limit: int,
        anchor_line: int | None,
        max_levels: int,
        include_siblings: bool,
        include_header: bool,
        max_lines: int | None,
    ) -> ToolResult:
        """Read file using indentation-aware mode."""
        from .readfile import IndentationOptions, read_file_with_indentation

        options = IndentationOptions(
            anchor_line=anchor_line,
            max_levels=max_levels,
            include_siblings=include_siblings,
            include_header=include_header,
            max_lines=max_lines,
        )

        blocks = read_file_with_indentation(file_path, offset, limit, options)

        content_parts = []
        for block in blocks:
            anchor_info = f" (anchor: L{block.get('anchor', offset)})" if block.get("anchor") else ""
            header = f"{file_path}:{block['start']}-{block['end']}{anchor_info}"
            content_parts.append(f"**{header}** [indentation mode]")

            for lineno, line in block["lines"]:
                content_parts.append(f"L{lineno}: {line}")

        content = "\n".join(content_parts)

        return ToolResult(
            success=True,
            content=content,
            metadata={
                "file_path": str(file_path),
                "mode": "indentation",
                "anchor_line": anchor_line or offset,
                "blocks_read": len(blocks),
                "total_lines": sum(len(block["lines"]) for block in blocks),
            },
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative to current working directory)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["slice", "indentation"],
                    "description": "Reading mode: 'slice' for line ranges, 'indentation' for smart block reading",
                },
                # Slice mode
                "ranges": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "[Slice mode] Line ranges like '1-200'",
                },
                "max_lines": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5000,
                    "description": "Maximum lines to return per block (default 400 for slice, 200 for indentation)",
                },
                # Indentation mode
                "offset": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "[Indentation mode] Starting line number (1-indexed)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2000,
                    "description": "[Indentation mode] Maximum lines to return (default 200)",
                },
                "anchor_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "[Indentation mode] Center line for expansion (defaults to offset)",
                },
                "max_levels": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "[Indentation mode] Parent indent levels to include. 0=unlimited, 1=immediate parent, etc.",
                },
                "include_siblings": {
                    "type": "boolean",
                    "description": "[Indentation mode] Include sibling blocks at same indentation",
                },
                "include_header": {
                    "type": "boolean",
                    "description": "[Indentation mode] Include comments/decorators above the block",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        }


class ThinkTool(BaseTool):
    """Tool for internal reasoning and planning."""

    @property
    def name(self) -> str:
        return "think"

    @property
    def description(self) -> str:
        return "Use this tool for internal reasoning, planning, and organizing your thoughts before taking action."

    def execute(self, thought: str) -> ToolResult:  # type: ignore[override]
        """Execute thinking process."""
        return ToolResult(success=True, content=f"🤔 Thinking: {thought}", metadata={"thought": thought})

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"thought": {"type": "string", "description": "Your thoughts, plans, or reasoning"}},
            "required": ["thought"],
            "additionalProperties": False,
        }


class BashTool(BaseTool):
    """Tool for executing bash commands."""

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute bash commands. Use for file operations, running scripts, or system commands. Returns stdout and stderr."

    def execute(self, command: str, timeout: int = 30) -> ToolResult:  # type: ignore[override]
        """Execute bash command."""
        import subprocess

        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)

            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"

            return ToolResult(
                success=result.returncode == 0,
                content=output or "(no output)",
                metadata={"command": command, "exit_code": result.returncode},
                error=None if result.returncode == 0 else f"Command exited with code {result.returncode}",
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error=f"Command timed out after {timeout} seconds")
        except Exception as e:
            return ToolResult(success=False, content="", error=f"Command failed: {type(e).__name__}: {e}")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Bash command to execute"},
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 600,
                    "description": "Timeout in seconds (default: 30)",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        }


class GrepTool(BaseTool):
    """Tool for searching files using ripgrep."""

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search for patterns in files using ripgrep. Returns matching lines with file paths and line numbers."

    def execute(  # type: ignore[override]
        self,
        pattern: str,
        paths: list[str] | None = None,
        ignore_case: bool = False,
        hidden: bool = False,
        context: int = 0,
        globs: list[str] | None = None,
    ) -> ToolResult:
        """Execute grep search."""
        import shutil
        import subprocess

        if shutil.which("rg") is None:
            return ToolResult(
                success=False, content="", error="ripgrep (rg) not found on PATH. Please install ripgrep."
            )

        try:
            cmd = ["rg", pattern, *(paths or ["."]), "-n"]
            if ignore_case:
                cmd.append("-i")
            if hidden:
                cmd.append("--hidden")
            if context:
                cmd.extend(["-C", str(context)])
            for g in globs or []:
                cmd.extend(["-g", g])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                return ToolResult(
                    success=True,
                    content=result.stdout,
                    metadata={
                        "pattern": pattern,
                        "paths": paths or ["."],
                        "match_count": len(result.stdout.splitlines()),
                    },
                )
            elif result.returncode == 1:
                # No matches found
                return ToolResult(
                    success=True, content="No matches found.", metadata={"pattern": pattern, "match_count": 0}
                )
            else:
                return ToolResult(
                    success=False,
                    content=result.stdout,
                    error=result.stderr or f"ripgrep exited with code {result.returncode}",
                )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error="Search timed out after 30 seconds")
        except Exception as e:
            return ToolResult(success=False, content="", error=f"Search failed: {type(e).__name__}: {e}")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Pattern to search for (regex supported)"},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Paths to search in (default: current directory)",
                },
                "ignore_case": {"type": "boolean", "description": "Case-insensitive search"},
                "hidden": {"type": "boolean", "description": "Search hidden files and directories"},
                "context": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Number of context lines to show around matches",
                },
                "globs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File glob patterns to filter (e.g., '*.py')",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }


class WriteFileTool(BaseTool):
    """Tool for writing content to files."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file. Creates new file or overwrites existing file."

    def execute(self, path: str, content: str) -> ToolResult:  # type: ignore[override]
        """Execute the write file tool."""
        from pathlib import Path

        try:
            file_path = Path(path).expanduser().resolve()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

            return ToolResult(
                success=True,
                content=f"Successfully wrote {len(content)} characters to {file_path}",
                metadata={"file_path": str(file_path), "size": len(content)},
            )
        except Exception as e:
            return ToolResult(success=False, content="", error=f"Failed to write file: {type(e).__name__}: {e}")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }


class ApplyPatchTool(BaseTool):
    """Tool for applying diff-based patches to files.

    This tool provides a more efficient and precise way to edit files compared
    to write_file. It uses a structured patch format that:
    - Minimizes token usage (only sends diffs, not full files)
    - Uses context anchors for precise location matching
    - Supports batch operations (multiple files in one patch)
    - Provides atomic file operations (add, delete, update, rename)
    """

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return """Apply diff-based patches to files. More efficient than write_file for edits.

Patch Format:
*** Begin Patch
*** Add File: path/to/new.py
+line 1
+line 2

*** Update File: path/to/existing.py
@@ class ClassName
@@ def method_name():
 context line (space prefix)
-line to delete (minus prefix)
+line to add (plus prefix)
 more context

*** Delete File: path/to/obsolete.py
*** End Patch

Key features:
- Use @@ anchors to locate the right position (class names, function signatures)
- Include 3 lines of context before and after changes
- Prefix context lines with space, deletions with -, additions with +
- All paths must be relative (never absolute)

Example for fixing a bug:
*** Begin Patch
*** Update File: src/calculator.py
@@ def subtract(a, b):
     \"\"\"Subtract b from a.\"\"\"
-    return a + b
+    return a - b
*** End Patch"""

    def execute(self, patch: str) -> ToolResult:  # type: ignore[override]
        """Execute the apply patch tool.

        Args:
            patch: The patch content in the apply_patch format
        """
        from pathlib import Path

        from .apply_patch import PatchApplyError, PatchParseError, apply_patch_text

        try:
            changes = apply_patch_text(patch, Path.cwd())

            if not changes:
                return ToolResult(
                    success=True,
                    content="Patch applied but no changes were made.",
                    metadata={"changes": []},
                )

            # Format summary
            summary_parts = ["Patch applied successfully:"]
            total_additions = 0
            total_deletions = 0

            for change in changes:
                if change["type"] == "add":
                    summary_parts.append(f"  + Created: {change['path']} ({change['lines_added']} lines)")
                    total_additions += change["lines_added"]
                elif change["type"] == "delete":
                    summary_parts.append(f"  - Deleted: {change['path']}")
                elif change["type"] == "update":
                    additions = change.get("additions", 0)
                    deletions = change.get("deletions", 0)
                    target = change.get("target_path")
                    if target and target != change["path"]:
                        summary_parts.append(f"  ~ Updated: {change['path']} -> {target} (+{additions}/-{deletions})")
                    else:
                        summary_parts.append(f"  ~ Updated: {change['path']} (+{additions}/-{deletions})")
                    total_additions += additions
                    total_deletions += deletions

            summary_parts.append(f"\nTotal: +{total_additions}/-{total_deletions} lines")

            return ToolResult(
                success=True,
                content="\n".join(summary_parts),
                metadata={
                    "changes": changes,
                    "total_additions": total_additions,
                    "total_deletions": total_deletions,
                },
            )

        except PatchParseError as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Patch parse error: {e}. Check the patch format.",
            )
        except PatchApplyError as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Patch apply error: {e}. The file may have been modified.",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to apply patch: {type(e).__name__}: {e}",
            )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": (
                        "The patch content. Must start with '*** Begin Patch' and end with "
                        "'*** End Patch'. Use '*** Add File:', '*** Update File:', or "
                        "'*** Delete File:' for operations. In hunks, prefix context lines "
                        "with space, deletions with -, additions with +."
                    ),
                },
            },
            "required": ["patch"],
            "additionalProperties": False,
        }


class TodoTool(BaseTool):
    """Tool for managing a todo list to track tasks."""

    # Shared state across all instances
    _todos: list[dict[str, str]] = []

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return (
            "Manage a todo list to track tasks. Use action='read' to view current todos, "
            "action='write' with a complete list to update. Helps organize complex multi-step tasks."
        )

    def execute(self, action: str, todos: list[dict[str, str]] | None = None) -> ToolResult:  # type: ignore[override]
        """Execute todo operations."""
        if action == "read":
            return self._read_todos()
        elif action == "write":
            return self._write_todos(todos or [])
        else:
            return ToolResult(success=False, content="", error=f"Invalid action '{action}'. Use 'read' or 'write'.")

    def _read_todos(self) -> ToolResult:
        if not TodoTool._todos:
            return ToolResult(success=True, content="No todos.", metadata={"count": 0})

        lines = ["## Todo List", ""]
        for todo in TodoTool._todos:
            status = todo.get("status", "pending")
            content = todo.get("content", "")
            tid = todo.get("id", "")
            icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "cancelled": "❌"}.get(status, "⬜")
            lines.append(f"{icon} [{tid}] {content} ({status})")

        return ToolResult(success=True, content="\n".join(lines), metadata={"count": len(TodoTool._todos)})

    def _write_todos(self, todos: list[dict[str, str]]) -> ToolResult:
        # Validate todos
        valid_statuses = {"pending", "in_progress", "completed", "cancelled"}
        for i, todo in enumerate(todos):
            if "id" not in todo or "content" not in todo:
                return ToolResult(success=False, content="", error=f"Todo {i} missing 'id' or 'content'")
            if todo.get("status", "pending") not in valid_statuses:
                return ToolResult(success=False, content="", error=f"Invalid status for todo {todo['id']}")

        # Check unique IDs
        ids = [t["id"] for t in todos]
        if len(ids) != len(set(ids)):
            return ToolResult(success=False, content="", error="Todo IDs must be unique")

        TodoTool._todos = todos
        return ToolResult(
            success=True,
            content=f"Updated {len(todos)} todos.",
            metadata={"count": len(todos)},
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write"],
                    "description": "Action to perform: 'read' to view todos, 'write' to update the list",
                },
                "todos": {
                    "type": "array",
                    "description": "Complete list of todos (required for 'write' action)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique identifier for the todo"},
                            "content": {"type": "string", "description": "Description of the task"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "description": "Status of the todo (default: pending)",
                            },
                        },
                        "required": ["id", "content"],
                    },
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }


class ParallelTaskTool(BaseTool):
    """Tool for spawning parallel sub-agent tasks.

    This tool allows the agent to delegate work to sub-agents that execute
    tasks in parallel, enabling more efficient handling of complex requests.
    """

    def __init__(self, session_id: str | None = None):
        super().__init__()
        self.session_id = session_id

    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        return """Spawn and manage parallel sub-agent tasks.

This tool allows you to delegate work to specialized sub-agents that
run in parallel. Use this for:
- Exploring multiple files simultaneously
- Running analysis while continuing other work
- Breaking complex tasks into smaller parallel pieces

Actions:
- create: Create a new task for a sub-agent to execute
- status: Check the status of a task
- wait: Wait for a task to complete and get results
- cancel: Cancel a running task
- list: List all tasks

Agent Types:
- explorer: Fast read-only codebase exploration (50 steps max)
- planner: Analysis and planning (30 steps max)
- focused_coder: Specific implementation tasks (100 steps max)

Examples:
  Create: {"action": "create", "description": "Find all TODO comments", "agent_type": "explorer"}
  Check:  {"action": "status", "task_id": "abc123"}
  Wait:   {"action": "wait", "task_id": "abc123", "timeout": 60}
  List:   {"action": "list"}
"""

    def execute(  # type: ignore[override]
        self,
        action: str,
        description: str | None = None,
        agent_type: str = "focused_coder",
        task_id: str | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Execute the task tool."""
        import asyncio

        from .task import TaskTool

        tool = TaskTool(session_id=self.session_id)

        async def run_task():
            return await tool.execute(
                action=action,
                description=description,
                agent_type=agent_type,
                task_id=task_id,
                timeout=timeout,
            )

        try:
            # Check if we're already in an async context
            try:
                asyncio.get_running_loop()
                # We're in an async context, create a task and wait
                # Use nest_asyncio if available, otherwise use a different approach
                try:
                    import nest_asyncio

                    nest_asyncio.apply()
                    result = asyncio.run(run_task())
                except ImportError:
                    # Create task and get result via future
                    future = asyncio.ensure_future(run_task())
                    # We can't block here, so return a message about the task
                    if action == "create":
                        # For create action, we can run it synchronously
                        # by creating a new thread
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, run_task())
                            result = future.result(timeout=30)
                    else:
                        # For other actions, try to run in the current loop
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, run_task())
                            result = future.result(timeout=timeout or 30)
            except RuntimeError:
                # No running loop, safe to use asyncio.run
                result = asyncio.run(run_task())

            return ToolResult(success=True, content=result)
        except Exception as e:
            return ToolResult(success=False, content="", error=str(e))

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "status", "wait", "cancel", "list"],
                    "description": "Action to perform",
                },
                "description": {
                    "type": "string",
                    "description": "Task description (required for 'create' action)",
                },
                "agent_type": {
                    "type": "string",
                    "enum": ["explorer", "planner", "focused_coder"],
                    "description": "Type of agent for the task (default: focused_coder)",
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID (required for status/wait/cancel actions)",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds for wait action",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }


# Initialize default tool registry
def create_default_tool_registry(
    enable_write: bool = True,
    enable_apply_patch: bool = True,
    enable_task: bool = True,
    session_id: str | None = None,
) -> ToolRegistry:
    """Create a tool registry with default tools.

    Args:
        enable_write: Enable write_file tool
        enable_apply_patch: Enable apply_patch tool (recommended for file edits)
        enable_task: Enable task tool for parallel sub-agents
        session_id: Session ID for task tool
    """
    registry = ToolRegistry()

    # Register built-in tools
    registry.register(ReadFileTool())
    registry.register(GrepTool())
    registry.register(ThinkTool())
    registry.register(BashTool())
    registry.register(TodoTool())

    if enable_write:
        registry.register(WriteFileTool())
    if enable_apply_patch:
        registry.register(ApplyPatchTool())
    if enable_task:
        registry.register(ParallelTaskTool(session_id=session_id))

    return registry


# Global tool registry instance
_default_registry: ToolRegistry | None = None


def get_tool_registry(enable_write: bool | None = None) -> ToolRegistry:
    """Get the global tool registry instance."""
    global _default_registry
    if _default_registry is None:
        # Load config to determine defaults
        from .config import load_config

        cfg = load_config()
        chat_cfg = cfg.chat

        # Use config values if not explicitly provided
        if enable_write is None:
            enable_write = chat_cfg.write_tool_enabled if chat_cfg and chat_cfg.write_tool_enabled is not None else True

        _default_registry = create_default_tool_registry(enable_write=enable_write)
    return _default_registry


def register_tool(tool: BaseTool) -> None:
    """Register a tool with the global registry."""
    get_tool_registry().register(tool)
