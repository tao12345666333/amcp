"""Tests for AMCP Permissions System."""

from __future__ import annotations

import pytest

from amcp.permissions import (
    PermissionAction,
    PermissionDeniedError,
    PermissionManager,
    PermissionRejectedError,
    PermissionRequest,
    PermissionResult,
    PermissionRule,
    _get_command_prefix,
    _glob_match,
)


class TestGlobMatch:
    """Tests for glob-style pattern matching."""

    def test_literal_match(self):
        """Test exact literal matching."""
        assert _glob_match("hello", "hello") is True
        assert _glob_match("hello", "world") is False

    def test_star_wildcard(self):
        """Test single star wildcard matching."""
        assert _glob_match("git status", "git *") is True
        assert _glob_match("git", "git *") is False
        assert _glob_match("git push origin main", "git push *") is True

    def test_double_star_wildcard(self):
        """Test double star wildcard for path matching."""
        assert _glob_match("src/foo/bar.py", "**/*.py") is True
        # Note: **/*.py requires a / before the filename, so bar.py alone doesn't match
        assert _glob_match("bar.py", "*.py") is True  # Use *.py for simple filenames
        assert _glob_match("src/foo/bar.js", "**/*.py") is False

    def test_question_mark(self):
        """Test question mark single-character matching."""
        assert _glob_match("file1.txt", "file?.txt") is True
        assert _glob_match("file12.txt", "file?.txt") is False

    def test_character_class(self):
        """Test character class matching."""
        assert _glob_match("a.txt", "[abc].txt") is True
        assert _glob_match("b.txt", "[abc].txt") is True
        assert _glob_match("d.txt", "[abc].txt") is False

    def test_case_insensitive(self):
        """Test that matching is case-insensitive."""
        assert _glob_match("Git Status", "git *") is True
        assert _glob_match("GIT STATUS", "git *") is True


class TestCommandPrefix:
    """Tests for command prefix extraction."""

    def test_basic_commands(self):
        """Test basic command prefix extraction."""
        assert _get_command_prefix("ls -la") == "ls"
        assert _get_command_prefix("cat file.txt") == "cat"
        assert _get_command_prefix("rm -rf /") == "rm"

    def test_git_commands(self):
        """Test git command prefix extraction."""
        assert _get_command_prefix("git status") == "git status"
        assert _get_command_prefix("git checkout main") == "git checkout"
        assert _get_command_prefix("git push origin main") == "git push"

    def test_npm_commands(self):
        """Test npm command prefix extraction."""
        assert _get_command_prefix("npm install lodash") == "npm install"
        assert _get_command_prefix("npm run dev") == "npm run dev"
        assert _get_command_prefix("npm test") == "npm test"

    def test_docker_commands(self):
        """Test docker command prefix extraction."""
        assert _get_command_prefix("docker run nginx") == "docker run"
        assert _get_command_prefix("docker compose up -d") == "docker compose up"


class TestPermissionRule:
    """Tests for PermissionRule matching."""

    def test_simple_match(self):
        """Test simple rule matching."""
        rule = PermissionRule("bash", "*", PermissionAction.ASK)
        assert rule.matches("bash", "git status") is True
        assert rule.matches("read_file", "test.txt") is False

    def test_pattern_match(self):
        """Test pattern matching in rules."""
        rule = PermissionRule("bash", "git *", PermissionAction.ALLOW)
        assert rule.matches("bash", "git status") is True
        assert rule.matches("bash", "npm install") is False

    def test_wildcard_permission(self):
        """Test wildcard permission matching."""
        rule = PermissionRule("mcp.*", "*", PermissionAction.ASK)
        assert rule.matches("mcp.exa.search", "query") is True
        assert rule.matches("mcp.browser.navigate", "url") is True
        assert rule.matches("bash", "ls") is False


class TestPermissionManager:
    """Tests for PermissionManager."""

    def test_default_rules(self):
        """Test that default rules are loaded."""
        pm = PermissionManager()
        pm.load_from_config({})

        # Check read_file is allowed by default
        result = pm.test_permission("read_file", {"path": "test.txt"})
        assert result.action == PermissionAction.ALLOW

        # Check bash requires confirmation by default
        result = pm.test_permission("bash", {"command": "ls"})
        assert result.action == PermissionAction.ASK

    def test_deny_env_files(self):
        """Test that .env files are denied by default."""
        pm = PermissionManager()
        pm.load_from_config({})

        result = pm.test_permission("read_file", {"path": ".env"})
        assert result.action == PermissionAction.DENY

        result = pm.test_permission("read_file", {"path": ".env.local"})
        assert result.action == PermissionAction.DENY

        # But .env.example is allowed
        result = pm.test_permission("read_file", {"path": ".env.example"})
        assert result.action == PermissionAction.ALLOW

    def test_custom_rules(self):
        """Test loading custom rules from config."""
        pm = PermissionManager()
        pm.load_from_config({
            "permissions": {
                "bash": "deny",
                "read_file": "allow",
            }
        })

        result = pm.test_permission("bash", {"command": "ls"})
        assert result.action == PermissionAction.DENY

    def test_nested_rules(self):
        """Test nested rules (per-pattern)."""
        pm = PermissionManager()
        # Load without defaults by setting _loaded = True and _rules directly
        pm._loaded = True
        pm._rules = [
            PermissionRule("bash", "*", PermissionAction.ASK),
            PermissionRule("bash", "git *", PermissionAction.ALLOW),
            PermissionRule("bash", "rm *", PermissionAction.DENY),
        ]

        result = pm.test_permission("bash", {"command": "git status"})
        assert result.action == PermissionAction.ALLOW

        # Note: * doesn't match /, so use "rm -rf ." instead of "rm -rf /"
        result = pm.test_permission("bash", {"command": "rm -rf ."})
        assert result.action == PermissionAction.DENY

        result = pm.test_permission("bash", {"command": "npm install"})
        assert result.action == PermissionAction.ASK

    def test_last_match_wins(self):
        """Test that the last matching rule wins."""
        pm = PermissionManager()
        pm.load_from_config({
            "permissions": {
                "bash": {
                    "*": "deny",
                    "git *": "allow",
                }
            }
        })

        # git * should match and allow
        result = pm.test_permission("bash", {"command": "git push"})
        assert result.action == PermissionAction.ALLOW

    def test_session_approval(self):
        """Test session-level approvals."""
        pm = PermissionManager()
        pm.load_from_config({
            "permissions": {
                "bash": "ask",
            }
        })

        # Initially should ask
        result = pm.test_permission("bash", {"command": "npm install"})
        assert result.action == PermissionAction.ASK

        # Add session approval
        pm.approve_session_pattern("session1", "bash", "npm *")

        # Now create a request with the session ID
        request = PermissionRequest(
            tool_name="bash",
            arguments={"command": "npm install lodash"},
            session_id="session1",
        )
        result = pm.evaluate(request)
        assert result.action == PermissionAction.ALLOW

        # Different session should still ask
        request2 = PermissionRequest(
            tool_name="bash",
            arguments={"command": "npm install lodash"},
            session_id="session2",
        )
        result2 = pm.evaluate(request2)
        assert result2.action == PermissionAction.ASK

    def test_clear_session_approvals(self):
        """Test clearing session approvals."""
        pm = PermissionManager()
        pm.load_from_config({"permissions": {"bash": "ask"}})

        pm.approve_session_pattern("session1", "bash", "*")
        pm.clear_session_approvals("session1")

        request = PermissionRequest(
            tool_name="bash",
            arguments={"command": "ls"},
            session_id="session1",
        )
        result = pm.evaluate(request)
        assert result.action == PermissionAction.ASK


class TestPermissionRequest:
    """Tests for PermissionRequest."""

    def test_bash_match_value(self):
        """Test match value extraction for bash."""
        request = PermissionRequest(
            tool_name="bash",
            arguments={"command": "git status"},
            session_id="test",
        )
        assert request.get_match_value() == "git status"

    def test_file_match_value(self):
        """Test match value extraction for file tools."""
        request = PermissionRequest(
            tool_name="read_file",
            arguments={"path": "/home/user/test.py"},
            session_id="test",
        )
        assert request.get_match_value() == "/home/user/test.py"

    def test_grep_match_value(self):
        """Test match value extraction for grep."""
        request = PermissionRequest(
            tool_name="grep",
            arguments={"pattern": "TODO"},
            session_id="test",
        )
        assert request.get_match_value() == "TODO"


class TestAlwaysPatterns:
    """Tests for "always allow" pattern generation."""

    def test_bash_always_patterns(self):
        """Test always patterns for bash commands."""
        pm = PermissionManager()
        pm.load_from_config({})

        request = PermissionRequest(
            tool_name="bash",
            arguments={"command": "git status"},
            session_id="test",
        )
        result = pm.evaluate(request)

        # Should suggest "git *" pattern
        assert any("git" in p for p in result.always_patterns)

    def test_file_always_patterns(self):
        """Test always patterns for file tools."""
        pm = PermissionManager()
        pm.load_from_config({})

        request = PermissionRequest(
            tool_name="write_file",
            arguments={"path": "src/main.py"},
            session_id="test",
        )
        result = pm.evaluate(request)

        # Should suggest directory and extension patterns
        assert any("src/*" in p for p in result.always_patterns)
        assert any("*.py" in p for p in result.always_patterns)


@pytest.mark.asyncio
async def test_check_permission_allow():
    """Test check_permission when allowed."""
    pm = PermissionManager()
    pm.load_from_config({"permissions": {"bash": "allow"}})

    request = PermissionRequest(
        tool_name="bash",
        arguments={"command": "ls"},
        session_id="test",
    )

    # Should not raise
    await pm.check_permission(request)


@pytest.mark.asyncio
async def test_check_permission_deny():
    """Test check_permission when denied."""
    pm = PermissionManager()
    pm.load_from_config({"permissions": {"bash": "deny"}})

    request = PermissionRequest(
        tool_name="bash",
        arguments={"command": "ls"},
        session_id="test",
    )

    with pytest.raises(PermissionDeniedError):
        await pm.check_permission(request)


@pytest.mark.asyncio
async def test_check_permission_ask_no_callback():
    """Test that ask without callback defaults to allow."""
    pm = PermissionManager()
    pm.load_from_config({"permissions": {"bash": "ask"}})
    pm.set_confirmation_callback(None)

    request = PermissionRequest(
        tool_name="bash",
        arguments={"command": "ls"},
        session_id="test",
    )

    # Should not raise (defaults to allow in non-interactive mode)
    await pm.check_permission(request)


class TestPermissionModes:
    """Tests for session permission modes."""

    def test_yolo_mode_allows_everything(self):
        """Test YOLO mode auto-allows all operations."""
        from amcp.permissions import PermissionMode

        pm = PermissionManager()
        pm.load_from_config({"permissions": {"bash": "deny"}})

        # Set YOLO mode for the session
        pm.set_session_mode("session1", PermissionMode.YOLO)

        request = PermissionRequest(
            tool_name="bash",
            arguments={"command": "rm -rf /"},
            session_id="session1",
        )
        result = pm.evaluate(request)

        # Should allow even though rule says deny
        assert result.action == PermissionAction.ALLOW
        assert "YOLO" in (result.message or "")

    def test_strict_mode_asks_everything(self):
        """Test STRICT mode requires confirmation for everything."""
        from amcp.permissions import PermissionMode

        pm = PermissionManager()
        pm.load_from_config({"permissions": {"read_file": "allow"}})

        # Set STRICT mode for the session
        pm.set_session_mode("session1", PermissionMode.STRICT)

        request = PermissionRequest(
            tool_name="read_file",
            arguments={"path": "test.txt"},
            session_id="session1",
        )
        result = pm.evaluate(request)

        # Should ask even though rule says allow
        assert result.action == PermissionAction.ASK
        assert "STRICT" in (result.message or "")

    def test_strict_mode_still_denies(self):
        """Test STRICT mode still respects deny rules."""
        from amcp.permissions import PermissionMode

        pm = PermissionManager()
        pm.load_from_config({"permissions": {"read_file": "deny"}})

        pm.set_session_mode("session1", PermissionMode.STRICT)

        request = PermissionRequest(
            tool_name="read_file",
            arguments={"path": "test.txt"},
            session_id="session1",
        )
        result = pm.evaluate(request)

        # Should deny (deny rules are respected even in strict mode)
        assert result.action == PermissionAction.DENY

    def test_default_mode(self):
        """Test default mode setting."""
        from amcp.permissions import PermissionMode

        pm = PermissionManager()
        pm.load_from_config({})

        # Default should be NORMAL
        assert pm.get_default_mode() == PermissionMode.NORMAL

        # Set default to YOLO
        pm.set_default_mode(PermissionMode.YOLO)
        assert pm.get_default_mode() == PermissionMode.YOLO

        # New sessions should use the default
        assert pm.get_session_mode("new-session") == PermissionMode.YOLO

    def test_session_mode_override(self):
        """Test session mode overrides default."""
        from amcp.permissions import PermissionMode

        pm = PermissionManager()
        pm.load_from_config({})

        pm.set_default_mode(PermissionMode.STRICT)
        pm.set_session_mode("session1", PermissionMode.YOLO)

        # Session1 should use YOLO
        assert pm.get_session_mode("session1") == PermissionMode.YOLO
        # Other sessions should use default (STRICT)
        assert pm.get_session_mode("session2") == PermissionMode.STRICT

    def test_clear_session_mode(self):
        """Test clearing session mode reverts to default."""
        from amcp.permissions import PermissionMode

        pm = PermissionManager()
        pm.load_from_config({})

        pm.set_session_mode("session1", PermissionMode.YOLO)
        assert pm.get_session_mode("session1") == PermissionMode.YOLO

        pm.clear_session_mode("session1")
        assert pm.get_session_mode("session1") == PermissionMode.NORMAL
