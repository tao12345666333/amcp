"""Tests for the slash commands system."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from amcp.commands import (
    CommandContext,
    CommandKind,
    CommandManager,
    CommandResult,
    SlashCommand,
    get_command_manager,
    reset_command_manager,
)


@pytest.fixture
def temp_commands_dir():
    """Create a temporary commands directory."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_command_file(temp_commands_dir: Path):
    """Create a sample command file."""
    command_file = temp_commands_dir / "test.toml"
    command_file.write_text("""
description = "A test command"
prompt = "This is a test prompt with {{args}}"
""")
    return command_file


@pytest.fixture
def namespaced_command_file(temp_commands_dir: Path):
    """Create a namespaced command file."""
    subdir = temp_commands_dir / "git"
    subdir.mkdir()

    command_file = subdir / "commit.toml"
    command_file.write_text("""
description = "Generate commit message"
prompt = "Generate a commit message"
""")
    return command_file


@pytest.fixture
def command_manager():
    """Create a fresh command manager for each test."""
    reset_command_manager()
    return CommandManager()


class TestCommandManager:
    """Tests for CommandManager class."""

    def test_command_manager_creation(self, command_manager: CommandManager):
        """Test creating a command manager."""
        assert command_manager is not None
        # Built-in commands should not be registered without init
        assert command_manager.get_all_commands() == []

    def test_discover_commands_from_dir(
        self, command_manager: CommandManager, temp_commands_dir: Path, sample_command_file: Path
    ):
        """Test discovering commands from a directory."""
        commands = command_manager._discover_commands_from_dir(temp_commands_dir)

        assert len(commands) == 1
        assert "test" in commands
        cmd = commands["test"]
        assert cmd.name == "test"
        assert cmd.description == "A test command"

    def test_parse_command_file(
        self, command_manager: CommandManager, temp_commands_dir: Path, sample_command_file: Path
    ):
        """Test parsing a command file."""
        cmd = command_manager._parse_command_file(sample_command_file, temp_commands_dir)

        assert cmd is not None
        assert cmd.name == "test"
        assert cmd.description == "A test command"
        assert "{{args}}" in cmd.prompt_template

    def test_namespaced_commands(
        self, command_manager: CommandManager, temp_commands_dir: Path, namespaced_command_file: Path
    ):
        """Test namespaced commands from subdirectories."""
        commands = command_manager._discover_commands_from_dir(temp_commands_dir)

        assert "git:commit" in commands
        cmd = commands["git:commit"]
        assert cmd.name == "git:commit"

    def test_parse_input(self, command_manager: CommandManager):
        """Test parsing user input."""
        # Register a test command
        test_cmd = SlashCommand(
            name="test",
            description="Test",
            kind=CommandKind.FILE,
            prompt_template="Test prompt",
        )
        command_manager._commands["test"] = test_cmd

        # Parse command input
        cmd, args = command_manager.parse_input("/test hello world")
        assert cmd is not None
        assert cmd.name == "test"
        assert args == "hello world"

        # Non-slash input
        cmd, args = command_manager.parse_input("hello world")
        assert cmd is None
        assert args == "hello world"

    def test_execute_file_command(self, command_manager: CommandManager):
        """Test executing a file-based command."""
        test_cmd = SlashCommand(
            name="greet",
            description="Greet",
            kind=CommandKind.FILE,
            prompt_template="Hello {{args}}!",
        )
        command_manager._commands["greet"] = test_cmd

        result = command_manager.execute_command(test_cmd, "world")

        assert result.type == "submit_prompt"
        assert result.content == "Hello world!"

    def test_execute_builtin_command(self, command_manager: CommandManager):
        """Test executing a built-in command."""

        def custom_action(ctx: CommandContext, args: str) -> CommandResult:
            return CommandResult(type="message", content=f"Hello, {args}!")

        test_cmd = SlashCommand(
            name="hello",
            description="Say hello",
            kind=CommandKind.BUILT_IN,
            action=custom_action,
        )
        command_manager._commands["hello"] = test_cmd

        result = command_manager.execute_command(test_cmd, "world")

        assert result.type == "message"
        assert result.content == "Hello, world!"

    def test_default_args_handling(self, command_manager: CommandManager):
        """Test default argument handling when no {{args}} placeholder."""
        test_cmd = SlashCommand(
            name="analyze",
            description="Analyze",
            kind=CommandKind.FILE,
            prompt_template="Please analyze the code.",
        )
        command_manager._commands["analyze"] = test_cmd

        result = command_manager.execute_command(test_cmd, "my_file.py")

        assert result.type == "submit_prompt"
        assert "Please analyze the code." in result.content
        assert "/analyze my_file.py" in result.content  # Args appended


class TestTemplateProcessing:
    """Tests for template processing features."""

    @pytest.fixture
    def manager(self):
        reset_command_manager()
        return CommandManager()

    def test_args_replacement(self, manager: CommandManager):
        """Test {{args}} replacement."""
        cmd = SlashCommand(
            name="test",
            description="Test",
            kind=CommandKind.FILE,
            prompt_template="Search for: {{args}}",
        )

        context = CommandContext(
            raw_input="/test python",
            command_name="test",
            args="python",
        )

        result = manager._process_template(cmd.prompt_template, context)
        assert result == "Search for: python"

    def test_file_injection(self, manager: CommandManager, temp_commands_dir: Path):
        """Test @{path} file injection."""
        # Create a test file
        test_file = temp_commands_dir / "test.txt"
        test_file.write_text("File content here")

        context = CommandContext(
            raw_input="/test",
            command_name="test",
            args="",
            work_dir=temp_commands_dir,
        )

        template = f"Content: @{{{test_file.name}}}"
        result = manager._process_file_injections(template, context)

        assert "File content here" in result


class TestGlobalCommandManager:
    """Tests for global command manager functions."""

    def test_get_command_manager(self):
        """Test getting the global command manager."""
        reset_command_manager()
        cm = get_command_manager()
        assert cm is not None

        # Should have built-in commands
        commands = cm.get_all_commands()
        command_names = [c.name for c in commands]
        assert "help" in command_names
        assert "clear" in command_names
        assert "exit" in command_names
        assert "skills" in command_names

        # Same instance
        cm2 = get_command_manager()
        assert cm is cm2

    def test_reset_command_manager(self):
        """Test resetting the global command manager."""
        cm1 = get_command_manager()
        reset_command_manager()
        cm2 = get_command_manager()
        assert cm1 is not cm2


class TestBuiltinCommands:
    """Tests for built-in commands."""

    @pytest.fixture
    def manager(self):
        reset_command_manager()
        return get_command_manager()

    def test_help_command(self, manager: CommandManager):
        """Test the /help command."""
        cmd, _ = manager.parse_input("/help")
        assert cmd is not None

        result = manager.execute_command(cmd, "")
        assert result.type == "message"
        assert "Available" in result.content

    def test_exit_command(self, manager: CommandManager):
        """Test the /exit command."""
        cmd, _ = manager.parse_input("/exit")
        assert cmd is not None

        result = manager.execute_command(cmd, "")
        assert result.type == "handled"
        assert result.content == "exit"

    def test_clear_command(self, manager: CommandManager):
        """Test the /clear command."""
        cmd, _ = manager.parse_input("/clear")
        assert cmd is not None

        result = manager.execute_command(cmd, "")
        assert result.type == "handled"
        assert result.content == "clear"

    def test_info_command(self, manager: CommandManager):
        """Test the /info command."""
        cmd, _ = manager.parse_input("/info")
        assert cmd is not None

        result = manager.execute_command(cmd, "")
        assert result.type == "handled"
        assert result.content == "info"
