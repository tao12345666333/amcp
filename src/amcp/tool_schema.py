"""Repair and validation for model-supplied tool arguments.

Model providers frequently emit near-miss parameter names (``path`` instead of
``paths``) or scalars where arrays are expected. Passing those straight into a
tool's ``execute`` signature raises an opaque ``TypeError``, which costs a turn
and often pushes the model into abandoning the tool entirely (for example
falling back to ``bash`` + ``grep``).

This module repairs what can be repaired safely against the tool's published
JSON schema, and turns everything else into an actionable message the model can
correct on its next attempt.
"""

from __future__ import annotations

import difflib
import inspect
import json
from collections.abc import Callable, Mapping
from typing import Any

__all__ = [
    "IGNORED_PARAMETERS",
    "PARAMETER_ALIASES",
    "ToolArgumentError",
    "normalize_tool_arguments",
    "validate_callable_arguments",
]


class ToolArgumentError(Exception):
    """Raised when tool arguments cannot be repaired into a valid call."""


# Frequently hallucinated parameter names mapped to the canonical schema name.
# Alias keys are matched after case/separator folding, so ``filePath`` and
# ``file_path`` both resolve through the same entry.
PARAMETER_ALIASES: dict[str, dict[str, str]] = {
    "grep": {
        "path": "paths",
        "file": "paths",
        "files": "paths",
        "dir": "paths",
        "directory": "paths",
        "directories": "paths",
        "search_path": "paths",
        "search_paths": "paths",
        "regex": "pattern",
        "query": "pattern",
        "search": "pattern",
        "glob": "globs",
        "include": "globs",
        "file_pattern": "globs",
        "case_insensitive": "ignore_case",
        "context_lines": "context",
    },
    "read_file": {
        "file_path": "path",
        "filename": "path",
        "file": "path",
        "line_ranges": "ranges",
        "range": "ranges",
    },
    "write_file": {
        "file_path": "path",
        "filename": "path",
        "file": "path",
        "text": "content",
        "contents": "content",
        "data": "content",
    },
    "bash": {
        "cmd": "command",
        "commands": "command",
        "script": "command",
        "shell_command": "command",
        "timeout_seconds": "timeout",
    },
    "apply_patch": {
        "patch_text": "patch",
        "patches": "patch",
        "diff": "patch",
    },
    "think": {
        "thoughts": "thought",
        "reasoning": "thought",
        "text": "thought",
    },
    "todo": {
        "todo_list": "todos",
        "tasks": "todos",
        "items": "todos",
    },
    "task": {
        "task": "description",
        "prompt": "description",
        "type": "agent_type",
        "id": "task_id",
    },
    "memory": {
        "text": "content",
        "value": "content",
        "fact_key": "key",
        "tag": "tags",
        "limit": "max_results",
    },
    "session_search": {
        "q": "query",
        "search": "query",
        "text": "query",
        "limit": "max_results",
    },
    "web_search": {
        "q": "query",
        "search_query": "query",
        "keywords": "query",
        "num_results": "limit",
        "max_results": "limit",
        "count": "limit",
    },
    "web_fetch": {
        "link": "url",
        "uri": "url",
        "max_length": "max_chars",
        "max_characters": "max_chars",
    },
}

# Parameters that are dropped instead of rejected, because the runtime owns them.
# ``bash`` always runs in the trusted workspace root, so a model-supplied working
# directory is intentionally ignored rather than treated as a hard error.
IGNORED_PARAMETERS: dict[str, frozenset[str]] = {
    "bash": frozenset({"cwd", "workdir", "working_dir", "working_directory"}),
}

_TRUE_STRINGS = frozenset({"true", "yes", "y", "on", "1"})
_FALSE_STRINGS = frozenset({"false", "no", "n", "off", "0"})


def _fold(name: Any) -> str:
    """Fold a parameter name so case and separators do not matter."""
    return "".join(char for char in str(name).lower() if char.isalnum())


def _parameter_list(names: object) -> str:
    """Render a stable, model-friendly list of supported parameter names."""
    if isinstance(names, Mapping):
        candidates = list(names.keys())
    elif isinstance(names, (list, set, frozenset, tuple)):
        candidates = list(names)
    else:  # pragma: no cover - defensive
        candidates = []
    visible = sorted(str(name) for name in candidates if not str(name).startswith("_"))
    return ", ".join(visible) if visible else "(none)"


def _suggest(name: str, candidates: list[str]) -> str | None:
    """Return the closest supported parameter name, if there is an obvious one."""
    close = difflib.get_close_matches(name, candidates, n=1, cutoff=0.5)
    if close:
        return close[0]
    folded = _fold(name)
    for candidate in candidates:
        candidate_folded = _fold(candidate)
        if folded and (candidate_folded.startswith(folded) or folded.startswith(candidate_folded)):
            return candidate
    return None


def _unsupported_message(tool_name: str, unknown: list[Any], supported: object) -> str:
    supported_text = _parameter_list(supported)
    candidates = [part for part in supported_text.split(", ") if part != "(none)"]
    hints: list[str] = []
    for raw_name in unknown:
        name = str(raw_name)
        suggestion = _suggest(name, candidates)
        hints.append(f"'{name}'" + (f" (did you mean '{suggestion}'?)" if suggestion else ""))
    return (
        f"Tool '{tool_name}' does not support parameter(s): {', '.join(hints)}. Supported parameters: {supported_text}."
    )


def _missing_message(tool_name: str, missing: list[str], supported: object) -> str:
    return (
        f"Tool '{tool_name}' is missing required parameter(s): {', '.join(sorted(missing))}. "
        f"Supported parameters: {_parameter_list(supported)}."
    )


def _type_error(tool_name: str, name: str, expected: str, value: Any) -> ToolArgumentError:
    return ToolArgumentError(f"Tool '{tool_name}' parameter '{name}' must be {expected} (got {type(value).__name__})")


def _item_type(spec: Mapping[str, Any]) -> str | None:
    items = spec.get("items")
    if isinstance(items, Mapping):
        item_type = items.get("type")
        if isinstance(item_type, str):
            return item_type
    return None


def _coerce_array(tool_name: str, name: str, spec: Mapping[str, Any], value: Any) -> list[Any]:
    if isinstance(value, str):
        text = value.strip()
        parsed: Any = None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        items = parsed if isinstance(parsed, list) else [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    elif isinstance(value, Mapping):
        raise _type_error(tool_name, name, "an array", value)
    else:
        items = [value]

    if _item_type(spec) != "string":
        return items

    coerced: list[str] = []
    for item in items:
        if isinstance(item, str):
            coerced.append(item)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            coerced.append(str(item))
        else:
            raise _type_error(tool_name, name, "an array of strings", item)
    return coerced


def _coerce_object(tool_name: str, name: str, value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _type_error(tool_name, name, "an object", value) from exc
        if isinstance(parsed, dict):
            return parsed
    raise _type_error(tool_name, name, "an object", value)


def _coerce_boolean(tool_name: str, name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_STRINGS:
            return True
        if text in _FALSE_STRINGS:
            return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise _type_error(tool_name, name, "a boolean", value)


def _coerce_integer(tool_name: str, name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _type_error(tool_name, name, "an integer", value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise _type_error(tool_name, name, "an integer", value) from exc
    raise _type_error(tool_name, name, "an integer", value)


def _coerce_number(tool_name: str, name: str, value: Any) -> float | int:
    if isinstance(value, bool):
        raise _type_error(tool_name, name, "a number", value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise _type_error(tool_name, name, "a number", value) from exc
    raise _type_error(tool_name, name, "a number", value)


def _coerce_string(tool_name: str, name: str, value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    raise _type_error(tool_name, name, "a string", value)


def _check_bounds(tool_name: str, name: str, spec: Mapping[str, Any], value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    minimum = spec.get("minimum")
    maximum = spec.get("maximum")
    if isinstance(minimum, (int, float)) and value < minimum:
        raise ToolArgumentError(f"Tool '{tool_name}' parameter '{name}' must be >= {minimum} (got {value})")
    if isinstance(maximum, (int, float)) and value > maximum:
        raise ToolArgumentError(f"Tool '{tool_name}' parameter '{name}' must be <= {maximum} (got {value})")


def _coerce(tool_name: str, name: str, spec: Mapping[str, Any], value: Any) -> Any:
    """Coerce one value toward its declared JSON schema type."""
    if value is None:
        return None

    expected = spec.get("type")
    if isinstance(expected, list):
        expected = next((entry for entry in expected if entry != "null"), None)

    if expected == "array":
        value = _coerce_array(tool_name, name, spec, value)
    elif expected == "object":
        value = _coerce_object(tool_name, name, value)
    elif expected == "boolean":
        value = _coerce_boolean(tool_name, name, value)
    elif expected == "integer":
        value = _coerce_integer(tool_name, name, value)
    elif expected == "number":
        value = _coerce_number(tool_name, name, value)
    elif expected == "string":
        value = _coerce_string(tool_name, name, value)

    enum = spec.get("enum")
    if isinstance(enum, list) and enum and value not in enum:
        allowed = ", ".join(str(entry) for entry in enum)
        raise ToolArgumentError(f"Tool '{tool_name}' parameter '{name}' must be one of: {allowed} (got {value!r})")

    _check_bounds(tool_name, name, spec, value)
    return value


def normalize_tool_arguments(
    tool_name: str,
    schema: Mapping[str, Any] | None,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    """Return canonical arguments for a tool, repairing recoverable mistakes.

    Aliases are resolved to their schema name, scalars are widened to arrays,
    and stringified scalars are coerced to their declared type. Anything that
    cannot be repaired raises :class:`ToolArgumentError` with a message listing
    the supported parameters, so the model can fix the call instead of guessing.
    """
    if not isinstance(arguments, Mapping):
        raise ToolArgumentError(f"Arguments for tool '{tool_name}' must be a JSON object")

    schema = schema or {}
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return dict(arguments)

    aliases = {_fold(alias): target for alias, target in PARAMETER_ALIASES.get(tool_name, {}).items()}
    canonical = {_fold(name): name for name in properties}
    ignored = {_fold(name) for name in IGNORED_PARAMETERS.get(tool_name, frozenset())}

    resolved: dict[str, Any] = {}
    unknown: list[Any] = []
    for raw_name, value in arguments.items():
        folded = _fold(raw_name)
        if folded in ignored and folded not in canonical:
            continue
        name = canonical.get(folded) or canonical.get(_fold(aliases.get(folded, "")))
        if name is None:
            unknown.append(raw_name)
            continue
        # Never let an alias shadow an explicitly supplied canonical parameter.
        if name in resolved and folded != _fold(name):
            continue
        resolved[name] = value

    if unknown:
        if schema.get("additionalProperties") is False:
            raise ToolArgumentError(_unsupported_message(tool_name, unknown, properties))
        for raw_name in unknown:
            resolved.setdefault(str(raw_name), arguments[raw_name])

    normalized: dict[str, Any] = {}
    for name, value in resolved.items():
        spec = properties.get(name)
        normalized[name] = _coerce(tool_name, name, spec if isinstance(spec, Mapping) else {}, value)

    required = schema.get("required")
    if isinstance(required, list):
        missing = [str(name) for name in required if normalized.get(str(name)) is None]
        if missing:
            raise ToolArgumentError(_missing_message(tool_name, missing, properties))

    return normalized


def validate_callable_arguments(
    tool_name: str,
    func: Callable[..., Any],
    arguments: Mapping[str, Any],
) -> None:
    """Reject kwargs a tool cannot bind, before they become an opaque TypeError.

    This is the last line of defense for callers that skip
    :func:`normalize_tool_arguments` (direct registry calls, the HTTP execute
    endpoint, tests), so an unsupported parameter yields a readable message
    instead of ``TypeError: execute() got an unexpected keyword argument``.
    """
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):  # pragma: no cover - builtins without signatures
        return

    parameters = signature.parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return

    bindable = {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }
    accepted = {name for name, parameter in parameters.items() if parameter.kind in bindable}

    unknown = [name for name in arguments if name not in accepted]
    if unknown:
        raise ToolArgumentError(_unsupported_message(tool_name, unknown, accepted))

    missing = [
        name
        for name, parameter in parameters.items()
        if parameter.kind in bindable and parameter.default is inspect.Parameter.empty and name not in arguments
    ]
    if missing:
        raise ToolArgumentError(_missing_message(tool_name, missing, accepted))
