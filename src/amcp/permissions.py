"""AMCP Permissions System.

This module implements a flexible permission system that allows users to control
which tools and commands can be executed, which require confirmation, and which
should be blocked.

Features:
- Pattern-based matching with wildcards
- Tool-level and command-level rules
- Session-based "always allow" memory
- External program delegation
- Agent-specific permissions
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


class PermissionAction(str, Enum):
    """Permission actions that can be taken for a tool call."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    DELEGATE = "delegate"


class PermissionMode(str, Enum):
    """Session-level permission modes.

    These modes control the overall permission behavior for a session:
    - NORMAL: Follow configured rules (allow/ask/deny)
    - YOLO: Auto-allow all operations (dangerous but convenient for trusted tasks)
    - STRICT: Require confirmation for all operations (most secure)
    """

    NORMAL = "normal"  # Follow configured rules
    YOLO = "yolo"  # Auto-allow everything (You Only Live Once)
    STRICT = "strict"  # Ask for everything


@dataclass
class PermissionRule:
    """A single permission rule.

    Attributes:
        permission: The permission type (e.g., "bash", "read_file", "mcp.exa.*")
        pattern: The pattern to match against (e.g., "git *", "*.py")
        action: The action to take when matched
        delegate_to: For delegate action, the external program to call
    """

    permission: str
    pattern: str
    action: PermissionAction
    delegate_to: str | None = None

    def matches(self, permission_type: str, value: str) -> bool:
        """Check if this rule matches the given permission type and value.

        Args:
            permission_type: The permission type to match (e.g., "bash")
            value: The value to match against (e.g., "git status")

        Returns:
            True if this rule matches
        """
        # Match permission type using fnmatch (supports * wildcards)
        if not fnmatch.fnmatch(permission_type, self.permission):
            return False

        # Match pattern using glob-style matching
        return _glob_match(value, self.pattern)


@dataclass
class PermissionRequest:
    """A request for permission to execute a tool.

    Attributes:
        tool_name: Name of the tool being called
        arguments: Arguments passed to the tool
        session_id: The session ID making the request
        metadata: Additional context information
    """

    tool_name: str
    arguments: dict[str, Any]
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def get_match_value(self) -> str:
        """Get the value to match against permission patterns.

        Returns:
            The value to use for pattern matching
        """
        if self.tool_name == "bash":
            return str(self.arguments.get("command", ""))
        elif self.tool_name in ("read_file", "write_file"):
            return str(self.arguments.get("path", ""))
        elif self.tool_name == "apply_patch":
            # For apply_patch, we extract all file paths from the patch
            patch = str(self.arguments.get("patch", ""))
            files = _extract_patch_files(patch)
            return " ".join(files) if files else "*"
        elif self.tool_name == "grep":
            return str(self.arguments.get("pattern", ""))
        elif self.tool_name.startswith("mcp."):
            # For MCP tools, use the full tool name as the match value
            return json.dumps(self.arguments, ensure_ascii=False)
        else:
            # Default: use JSON representation of arguments
            return json.dumps(self.arguments, ensure_ascii=False)


@dataclass
class PermissionResult:
    """Result of a permission check.

    Attributes:
        action: The action to take
        matched_rule: The rule that matched (if any)
        message: Optional message for the user
        always_patterns: Suggested patterns for "always allow"
    """

    action: PermissionAction
    matched_rule: PermissionRule | None = None
    message: str | None = None
    always_patterns: list[str] = field(default_factory=list)


class PermissionDeniedError(Exception):
    """Raised when permission is denied."""

    def __init__(self, message: str, rule: PermissionRule | None = None):
        super().__init__(message)
        self.rule = rule


class PermissionRejectedError(Exception):
    """Raised when user rejects a permission request."""

    def __init__(self, message: str = "User rejected the permission request"):
        super().__init__(message)


@runtime_checkable
class PermissionCallback(Protocol):
    """Protocol for permission confirmation callbacks."""

    async def __call__(self, request: PermissionRequest, result: PermissionResult) -> str:
        """Request permission confirmation from user.

        Args:
            request: The permission request
            result: The current permission result

        Returns:
            One of: "once", "always", "reject"
        """
        ...


class PermissionManager:
    """Manages permission rules and evaluates permission requests.

    This class is the main entry point for the permission system. It loads
    permission rules from configuration, evaluates requests against them,
    and manages session-level "always allow" patterns.
    """

    # Built-in default rules
    DEFAULT_RULES: list[PermissionRule] = [
        # Read-only operations default to allow
        PermissionRule("read_file", "*", PermissionAction.ALLOW),
        PermissionRule("grep", "*", PermissionAction.ALLOW),
        PermissionRule("think", "*", PermissionAction.ALLOW),
        PermissionRule("todo", "*", PermissionAction.ALLOW),
        # Protect sensitive files
        PermissionRule("read_file", "*.env", PermissionAction.DENY),
        PermissionRule("read_file", "*.env.*", PermissionAction.DENY),
        PermissionRule("read_file", ".env.example", PermissionAction.ALLOW),
        # Write operations require confirmation
        PermissionRule("bash", "*", PermissionAction.ASK),
        PermissionRule("write_file", "*", PermissionAction.ASK),
        PermissionRule("apply_patch", "*", PermissionAction.ASK),
        PermissionRule("task", "*", PermissionAction.ASK),
        # MCP tools require confirmation
        PermissionRule("mcp.*", "*", PermissionAction.ASK),
        # Safety guards
        PermissionRule("external_path", "*", PermissionAction.ASK),
        PermissionRule("doom_loop", "*", PermissionAction.ASK),
    ]

    def __init__(self):
        self._rules: list[PermissionRule] = []
        self._session_approved: dict[str, list[PermissionRule]] = {}
        self._session_modes: dict[str, PermissionMode] = {}
        self._default_mode: PermissionMode = PermissionMode.NORMAL
        self._confirmation_callback: PermissionCallback | None = None
        self._loaded = False

    def set_default_mode(self, mode: PermissionMode) -> None:
        """Set the default permission mode for new sessions.

        Args:
            mode: The default mode to use
        """
        self._default_mode = mode

    def get_default_mode(self) -> PermissionMode:
        """Get the default permission mode.

        Returns:
            The default permission mode
        """
        return self._default_mode

    def set_session_mode(self, session_id: str, mode: PermissionMode) -> None:
        """Set the permission mode for a specific session.

        Args:
            session_id: The session ID
            mode: The permission mode to use
        """
        self._session_modes[session_id] = mode

    def get_session_mode(self, session_id: str) -> PermissionMode:
        """Get the permission mode for a specific session.

        Args:
            session_id: The session ID

        Returns:
            The session's permission mode, or the default if not set
        """
        return self._session_modes.get(session_id, self._default_mode)

    def clear_session_mode(self, session_id: str) -> None:
        """Clear the permission mode for a session (revert to default).

        Args:
            session_id: The session ID
        """
        self._session_modes.pop(session_id, None)

    def set_confirmation_callback(self, callback: PermissionCallback | None) -> None:
        """Set the callback for permission confirmation requests.

        Args:
            callback: The callback function, or None to disable confirmation
        """
        self._confirmation_callback = callback

    def load_from_config(self, config_data: dict[str, Any] | None = None) -> None:
        """Load permission rules from configuration.

        Args:
            config_data: Optional configuration data. If not provided,
                        loads from the default config file.
        """
        if config_data is None:
            config_data = self._load_config_file()

        self._rules = list(self.DEFAULT_RULES)

        permissions_data = config_data.get("permissions", {})
        self._rules.extend(self._parse_permissions(permissions_data))
        self._loaded = True

    def _load_config_file(self) -> dict[str, Any]:
        """Load configuration from file.

        Returns:
            Configuration dictionary
        """
        # Try project-level config first
        project_config = Path.cwd() / ".amcp" / "permissions.toml"
        if project_config.exists():
            return tomllib.loads(project_config.read_text(encoding="utf-8"))

        # Fall back to global config
        global_config = Path.home() / ".config" / "amcp" / "config.toml"
        if global_config.exists():
            return tomllib.loads(global_config.read_text(encoding="utf-8"))

        return {}

    def _parse_permissions(self, data: dict[str, Any]) -> list[PermissionRule]:
        """Parse permissions section from config.

        Args:
            data: The permissions section of the config

        Returns:
            List of permission rules
        """
        rules: list[PermissionRule] = []

        for key, value in data.items():
            if isinstance(value, str):
                # Simple rule: permission = "action"
                action = PermissionAction(value)
                rules.append(PermissionRule(key, "*", action))
            elif isinstance(value, dict):
                if "action" in value and "to" in value:
                    # Delegate rule: permission = { action = "delegate", to = "program" }
                    rules.append(
                        PermissionRule(key, "*", PermissionAction.DELEGATE, delegate_to=value["to"])
                    )
                else:
                    # Nested rules: [permissions.bash]
                    for pattern, action_str in value.items():
                        if isinstance(action_str, str):
                            action = PermissionAction(action_str)
                            rules.append(PermissionRule(key, pattern, action))
                        elif isinstance(action_str, dict):
                            # Delegate for specific pattern
                            if action_str.get("action") == "delegate":
                                rules.append(
                                    PermissionRule(
                                        key,
                                        pattern,
                                        PermissionAction.DELEGATE,
                                        delegate_to=action_str.get("to"),
                                    )
                                )

        return rules

    def evaluate(self, request: PermissionRequest) -> PermissionResult:
        """Evaluate a permission request against the rules.

        Args:
            request: The permission request to evaluate

        Returns:
            PermissionResult indicating what action to take
        """
        if not self._loaded:
            self.load_from_config()

        tool_name = request.tool_name
        match_value = request.get_match_value()

        # Check session mode first (highest priority)
        session_mode = self.get_session_mode(request.session_id)

        if session_mode == PermissionMode.YOLO:
            # YOLO mode: auto-allow everything
            return PermissionResult(
                action=PermissionAction.ALLOW,
                message="YOLO mode: auto-allowed",
                always_patterns=self._generate_always_patterns(request),
            )

        if session_mode == PermissionMode.STRICT:
            # STRICT mode: ask for everything (but still check deny rules)
            # First check if there's a deny rule
            for rule in self._rules:
                if rule.matches(tool_name, match_value) and rule.action == PermissionAction.DENY:
                    return PermissionResult(
                        action=PermissionAction.DENY,
                        matched_rule=rule,
                        always_patterns=self._generate_always_patterns(request),
                    )
            # Otherwise ask
            return PermissionResult(
                action=PermissionAction.ASK,
                message="STRICT mode: confirmation required",
                always_patterns=self._generate_always_patterns(request),
            )

        # NORMAL mode: follow configured rules
        # Check session-approved rules first (highest priority in normal mode)
        session_rules = self._session_approved.get(request.session_id, [])
        for rule in reversed(session_rules):
            if rule.matches(tool_name, match_value):
                return PermissionResult(
                    action=rule.action,
                    matched_rule=rule,
                    always_patterns=self._generate_always_patterns(request),
                )

        # Check configured rules (last matching rule wins)
        matched_rule: PermissionRule | None = None
        for rule in self._rules:
            if rule.matches(tool_name, match_value):
                matched_rule = rule

        if matched_rule:
            return PermissionResult(
                action=matched_rule.action,
                matched_rule=matched_rule,
                always_patterns=self._generate_always_patterns(request),
            )

        # Default: ask
        return PermissionResult(
            action=PermissionAction.ASK,
            always_patterns=self._generate_always_patterns(request),
        )

    def _generate_always_patterns(self, request: PermissionRequest) -> list[str]:
        """Generate suggested patterns for "always allow".

        Args:
            request: The permission request

        Returns:
            List of suggested patterns
        """
        patterns: list[str] = []
        tool_name = request.tool_name

        if tool_name == "bash":
            command = request.arguments.get("command", "")
            prefix = _get_command_prefix(command)
            if prefix:
                patterns.append(f"{prefix} *")
            # Also add the exact command
            patterns.append(command)
        elif tool_name in ("read_file", "write_file"):
            path = request.arguments.get("path", "")
            # Add directory pattern
            if "/" in path:
                dir_path = path.rsplit("/", 1)[0]
                patterns.append(f"{dir_path}/*")
            # Add file pattern
            if "." in path:
                ext = path.rsplit(".", 1)[1]
                patterns.append(f"*.{ext}")
            patterns.append(path)
        elif tool_name == "grep":
            patterns.append(request.arguments.get("pattern", "*"))
        elif tool_name.startswith("mcp."):
            # For MCP tools, suggest the specific tool
            patterns.append("*")
        else:
            patterns.append("*")

        return patterns

    async def check_permission(self, request: PermissionRequest) -> None:
        """Check permission for a request, prompting user if needed.

        Args:
            request: The permission request to check

        Raises:
            PermissionDeniedError: If permission is denied by rule
            PermissionRejectedError: If user rejects the request
        """
        result = self.evaluate(request)

        if result.action == PermissionAction.ALLOW:
            return

        if result.action == PermissionAction.DENY:
            raise PermissionDeniedError(
                f"Permission denied for {request.tool_name}: {result.message or 'blocked by rule'}",
                result.matched_rule,
            )

        if result.action == PermissionAction.DELEGATE:
            delegate_result = await self._delegate_permission(request, result)
            if delegate_result == "allow":
                return
            elif delegate_result == "deny":
                raise PermissionDeniedError(
                    f"Permission denied by delegate: {result.matched_rule.delegate_to if result.matched_rule else 'unknown'}",
                    result.matched_rule,
                )
            # Fall through to ask

        # ASK action
        if self._confirmation_callback is None:
            # No callback set, default to allow (non-interactive mode)
            return

        response = await self._confirmation_callback(request, result)

        if response == "reject":
            raise PermissionRejectedError()

        if response == "always":
            # Add session-level approval
            if request.session_id not in self._session_approved:
                self._session_approved[request.session_id] = []

            for pattern in result.always_patterns[:1]:  # Use first suggested pattern
                self._session_approved[request.session_id].append(
                    PermissionRule(request.tool_name, pattern, PermissionAction.ALLOW)
                )

    async def _delegate_permission(
        self, request: PermissionRequest, result: PermissionResult
    ) -> str:
        """Delegate permission decision to external program.

        Args:
            request: The permission request
            result: The permission result containing delegate info

        Returns:
            "allow", "ask", or "deny"
        """
        if not result.matched_rule or not result.matched_rule.delegate_to:
            return "ask"

        program = result.matched_rule.delegate_to

        try:
            env = os.environ.copy()
            env["AMCP_TOOL_NAME"] = request.tool_name

            proc = await asyncio.create_subprocess_exec(
                program,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            input_data = json.dumps(
                {
                    "tool": request.tool_name,
                    "arguments": request.arguments,
                    "session_id": request.session_id,
                    "metadata": request.metadata,
                },
                ensure_ascii=False,
            ).encode()

            stdout, stderr = await proc.communicate(input_data)

            if proc.returncode == 0:
                return "allow"
            elif proc.returncode == 1:
                return "ask"
            else:  # returncode >= 2
                return "deny"

        except Exception:
            # If delegation fails, fall back to ask
            return "ask"

    def approve_session_pattern(
        self, session_id: str, permission: str, pattern: str
    ) -> None:
        """Add a session-level approval pattern.

        Args:
            session_id: The session to add approval for
            permission: The permission type
            pattern: The pattern to allow
        """
        if session_id not in self._session_approved:
            self._session_approved[session_id] = []

        self._session_approved[session_id].append(
            PermissionRule(permission, pattern, PermissionAction.ALLOW)
        )

    def clear_session_approvals(self, session_id: str) -> None:
        """Clear all session-level approvals.

        Args:
            session_id: The session to clear approvals for
        """
        self._session_approved.pop(session_id, None)

    def add_rule(self, rule: PermissionRule) -> None:
        """Add a permission rule.

        Args:
            rule: The rule to add
        """
        self._rules.append(rule)

    def get_rules(self) -> list[PermissionRule]:
        """Get all configured rules.

        Returns:
            List of permission rules
        """
        if not self._loaded:
            self.load_from_config()
        return list(self._rules)

    def test_permission(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> PermissionResult:
        """Test a permission without executing.

        Args:
            tool_name: The tool name to test
            arguments: The arguments to test

        Returns:
            The permission result that would be returned
        """
        request = PermissionRequest(
            tool_name=tool_name,
            arguments=arguments,
            session_id="test",
        )
        return self.evaluate(request)


def _glob_match(value: str, pattern: str) -> bool:
    """Match a value against a glob-style pattern.

    Supports:
    - * for any characters (not crossing path separators)
    - ** for any characters (including path separators)
    - ? for single character
    - [abc] for character sets

    Args:
        value: The value to match
        pattern: The glob pattern

    Returns:
        True if the value matches the pattern
    """
    # Convert glob pattern to regex
    regex_parts = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # ** matches anything including /
                regex_parts.append(".*")
                i += 2
            else:
                # * matches anything except /
                regex_parts.append("[^/]*")
                i += 1
        elif c == "?":
            regex_parts.append("[^/]")
            i += 1
        elif c == "[":
            # Find matching ]
            j = i + 1
            while j < len(pattern) and pattern[j] != "]":
                j += 1
            if j < len(pattern):
                regex_parts.append(pattern[i : j + 1])
                i = j + 1
            else:
                regex_parts.append(re.escape(c))
                i += 1
        else:
            regex_parts.append(re.escape(c))
            i += 1

    regex = "^" + "".join(regex_parts) + "$"
    return bool(re.match(regex, value, re.IGNORECASE))


def _get_command_prefix(command: str) -> str | None:
    """Extract the command prefix for "always allow" patterns.

    This function identifies the "human-understandable" command prefix
    from a shell command. For example:
    - "git checkout main" -> "git checkout"
    - "npm install lodash" -> "npm install"
    - "ls -la" -> "ls"

    Args:
        command: The full command line

    Returns:
        The command prefix, or None if unable to parse
    """
    # Command arity table - how many tokens define the command
    ARITY: dict[str, int] = {
        # Basic commands
        "cat": 1,
        "cd": 1,
        "chmod": 1,
        "chown": 1,
        "cp": 1,
        "echo": 1,
        "grep": 1,
        "ls": 1,
        "mkdir": 1,
        "mv": 1,
        "rm": 1,
        "touch": 1,
        "head": 1,
        "tail": 1,
        "find": 1,
        "which": 1,
        # Git
        "git": 2,
        "git config": 3,
        "git remote": 3,
        "git stash": 3,
        # Package managers
        "npm": 2,
        "npm run": 3,
        "npm exec": 3,
        "pnpm": 2,
        "pnpm run": 3,
        "yarn": 2,
        "yarn run": 3,
        "pip": 2,
        "poetry": 2,
        "cargo": 2,
        "cargo add": 3,
        "go": 2,
        # Docker
        "docker": 2,
        "docker compose": 3,
        "docker container": 3,
        "docker image": 3,
        # Make/build tools
        "make": 2,
        "cmake": 2,
        "bazel": 2,
        # Python
        "python": 2,
        "python3": 2,
    }

    try:
        tokens = shlex.split(command)
        if not tokens:
            return None

        # Try progressively shorter prefixes
        for length in range(len(tokens), 0, -1):
            prefix = " ".join(tokens[:length])
            arity = ARITY.get(prefix)
            if arity is not None:
                return " ".join(tokens[:arity])

        # Default: return just the first token
        return tokens[0]

    except ValueError:
        # shlex.split failed
        return command.split()[0] if command.strip() else None


def _extract_patch_files(patch: str) -> list[str]:
    """Extract file paths from a patch.

    Args:
        patch: The patch content

    Returns:
        List of file paths mentioned in the patch
    """
    files: list[str] = []
    for line in patch.split("\n"):
        line = line.strip()
        if line.startswith("*** Add File:"):
            files.append(line[13:].strip())
        elif line.startswith("*** Update File:") or line.startswith("*** Delete File:"):
            files.append(line[16:].strip())
        elif line.startswith("*** Rename File:"):
            # Format: *** Rename File: old -> new
            parts = line[16:].split("->")
            if len(parts) == 2:
                files.append(parts[0].strip())
                files.append(parts[1].strip())
    return files


# Global permission manager instance
_permission_manager: PermissionManager | None = None


def get_permission_manager() -> PermissionManager:
    """Get the global permission manager instance.

    Returns:
        The permission manager
    """
    global _permission_manager
    if _permission_manager is None:
        _permission_manager = PermissionManager()
    return _permission_manager


def reset_permission_manager() -> None:
    """Reset the global permission manager instance.

    Useful for testing or reloading configuration.
    """
    global _permission_manager
    _permission_manager = None
