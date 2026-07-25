"""Tests for model-supplied tool argument repair and validation."""

import shutil

import pytest

from amcp.config import AMCPConfig
from amcp.tool_execution import ToolCapability, ToolExecutionContext, ToolExecutor
from amcp.tool_schema import (
    ToolArgumentError,
    normalize_tool_arguments,
    validate_callable_arguments,
)
from amcp.tools import GrepTool, ReadFileTool, create_default_tool_registry

requires_ripgrep = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep (rg) is not installed")


def _grep_schema():
    return GrepTool().get_parameters_schema()


def _executor(tmp_path, exposed=None):
    return ToolExecutor(
        context=ToolExecutionContext("session", tmp_path, "turn"),
        capability=ToolCapability.from_spec(None, [], True),
        exposed_tools=exposed or {"grep", "read_file", "bash", "web_search"},
        registry=create_default_tool_registry(enable_task=False),
        mcp_registry={},
        config=AMCPConfig(servers={}, chat=None),
    )


def test_grep_path_alias_is_repaired_to_paths():
    args = normalize_tool_arguments("grep", _grep_schema(), {"pattern": "api_type", "path": "src"})

    assert args == {"pattern": "api_type", "paths": ["src"]}


def test_explicit_paths_wins_over_alias():
    for arguments in (
        {"pattern": "x", "path": "alias", "paths": ["canonical"]},
        {"pattern": "x", "paths": ["canonical"], "path": "alias"},
    ):
        assert normalize_tool_arguments("grep", _grep_schema(), arguments)["paths"] == ["canonical"]


def test_scalar_and_json_string_values_are_widened_to_arrays():
    schema = _grep_schema()

    assert normalize_tool_arguments("grep", schema, {"pattern": "x", "globs": "*.py"})["globs"] == ["*.py"]
    assert normalize_tool_arguments("grep", schema, {"pattern": "x", "paths": '["a", "b"]'})["paths"] == ["a", "b"]


def test_stringified_scalars_are_coerced_to_declared_types():
    args = normalize_tool_arguments(
        "grep",
        _grep_schema(),
        {"pattern": "x", "ignore_case": "true", "context": "3"},
    )

    assert args["ignore_case"] is True
    assert args["context"] == 3


def test_unknown_parameter_reports_supported_names_and_suggestion():
    with pytest.raises(ToolArgumentError) as excinfo:
        normalize_tool_arguments("grep", _grep_schema(), {"pattern": "x", "pattrn": "y"})

    message = str(excinfo.value)
    assert "'pattrn'" in message
    assert "did you mean 'pattern'?" in message
    assert "Supported parameters: context, globs, hidden, ignore_case, paths, pattern" in message


def test_missing_required_parameter_is_reported():
    with pytest.raises(ToolArgumentError, match="missing required parameter"):
        normalize_tool_arguments("grep", _grep_schema(), {"paths": ["src"]})


def test_enum_and_bound_violations_are_reported():
    read_schema = ReadFileTool().get_parameters_schema()

    with pytest.raises(ToolArgumentError, match="must be one of: slice, indentation"):
        normalize_tool_arguments("read_file", read_schema, {"path": "a.py", "mode": "lines"})
    with pytest.raises(ToolArgumentError, match="must be <= 5000"):
        normalize_tool_arguments("read_file", read_schema, {"path": "a.py", "max_lines": 99999})


def test_runtime_owned_bash_cwd_is_dropped_not_rejected():
    from amcp.tools import BashTool

    args = normalize_tool_arguments("bash", BashTool().get_parameters_schema(), {"cmd": "ls", "cwd": "/tmp"})

    assert args == {"command": "ls"}


def test_signature_guard_replaces_typeerror_with_actionable_message():
    with pytest.raises(ToolArgumentError) as excinfo:
        validate_callable_arguments("grep", GrepTool().execute, {"pattern": "x", "path": "src"})

    assert "did you mean 'paths'?" in str(excinfo.value)


def test_registry_reports_invalid_arguments_instead_of_typeerror():
    registry = create_default_tool_registry(enable_task=False)

    result = registry.execute_tool("grep", pattern="x", path="src")

    assert not result.success
    assert result.error is not None
    assert "TypeError" not in result.error
    assert "Invalid arguments" in result.error
    assert "did you mean 'paths'?" in result.error


@requires_ripgrep
def test_grep_tool_accepts_a_single_path_string(tmp_path):
    (tmp_path / "sample.py").write_text("active_provider = 'openai'\n", encoding="utf-8")

    result = GrepTool().execute(pattern="active_provider", paths=str(tmp_path))

    assert result.success
    assert "active_provider" in result.content
    assert result.metadata["paths"] == [str(tmp_path)]


@requires_ripgrep
@pytest.mark.asyncio
async def test_executor_repairs_grep_path_alias_within_workspace(tmp_path):
    (tmp_path / "config.py").write_text("api_type = 'openai'\n", encoding="utf-8")

    result = await _executor(tmp_path).execute("grep", {"pattern": "api_type", "path": "config.py"})

    assert result.success
    assert "api_type" in result.content
    assert result.metadata["paths"] == [str((tmp_path / "config.py").resolve())]


@pytest.mark.asyncio
async def test_executor_returns_actionable_error_for_unsupported_parameter(tmp_path):
    result = await _executor(tmp_path).execute("grep", {"pattern": "x", "recursive": True})

    assert not result.success
    assert result.error is not None
    assert "does not support parameter(s): 'recursive'" in result.error
    assert "Supported parameters" in result.error
