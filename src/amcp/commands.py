"""
Slash Commands system for AMCP.

Slash commands are custom command shortcuts that can be invoked using
the `/command` syntax. They are defined as TOML files containing:
- prompt: The prompt text to submit to the agent
- description: (optional) A brief description of the command

Commands are discovered from:
- User commands: ~/.config/amcp/commands/*.toml
- Project commands: .amcp/commands/*.toml (takes precedence)

Naming convention:
- Subdirectories create namespaced commands separated by ':'
- Example: .amcp/commands/git/commit.toml -> /git:commit
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

if TYPE_CHECKING:
    pass

# Default config directory
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "amcp"

# Placeholder patterns
ARGS_PLACEHOLDER = re.compile(r"\{\{args\}\}")
SHELL_INJECTION = re.compile(r"!\{([^}]+)\}")
FILE_INJECTION = re.compile(r"@\{([^}]+)\}")


class CommandKind(Enum):
    """Type of command."""

    BUILT_IN = "built_in"
    FILE = "file"
    DYNAMIC = "dynamic"


@dataclass
class CommandResult:
    """Result from executing a slash command."""

    type: str  # 'submit_prompt', 'message', 'handled'
    content: str = ""
    message_type: str = "info"  # 'info', 'error', 'success'


@dataclass
class SlashCommand:
    """Definition of a slash command."""

    name: str
    description: str
    kind: CommandKind
    source_file: str | None = None

    # For file-based commands: the prompt template
    prompt_template: str | None = None

    # For built-in or dynamic commands: the action function
    action: Callable[[CommandContext, str], CommandResult] | None = None

    # Subcommands for hierarchical commands
    subcommands: list[SlashCommand] = field(default_factory=list)

    # Whether to auto-execute on selection
    auto_execute: bool = True


@dataclass
class CommandContext:
    """Context passed to command handlers."""

    raw_input: str  # The full raw input from user
    command_name: str  # The matched command name
    args: str  # Arguments after the command name
    work_dir: Path | None = None
    project_root: Path | None = None


@dataclass
class CommandManager:
    """
    Manages the discovery and execution of slash commands.

    Commands can be discovered from user-level and project-level directories.
    Project commands take precedence over user commands with the same name.
    """

    _commands: dict[str, SlashCommand] = field(default_factory=dict)
    _builtin_commands: dict[str, SlashCommand] = field(default_factory=dict)

    @staticmethod
    def get_user_commands_dir() -> Path:
        """Get the user-level commands directory."""
        return CONFIG_DIR / "commands"

    @staticmethod
    def get_project_commands_dir(project_root: Path | None = None) -> Path:
        """Get the project-level commands directory."""
        root = project_root or Path.cwd()
        return root / ".amcp" / "commands"

    def register_builtin(self, command: SlashCommand) -> None:
        """Register a built-in command."""
        self._builtin_commands[command.name] = command
        # Also add to _commands so it's immediately available
        self._commands[command.name] = command

    def discover_commands(self, project_root: Path | None = None) -> None:
        """
        Discover commands from standard user and project locations.

        Project commands take precedence over user commands with the same name.

        Args:
            project_root: The project root directory (defaults to cwd)
        """
        # Start with built-in commands
        self._commands = dict(self._builtin_commands)

        # Discover user commands
        user_dir = self.get_user_commands_dir()
        user_commands = self._discover_commands_from_dir(user_dir)
        for name, cmd in user_commands.items():
            self._commands[name] = cmd

        # Discover project commands (takes precedence)
        project_dir = self.get_project_commands_dir(project_root)
        project_commands = self._discover_commands_from_dir(project_dir)
        for name, cmd in project_commands.items():
            self._commands[name] = cmd

    def _discover_commands_from_dir(self, commands_dir: Path) -> dict[str, SlashCommand]:
        """
        Discover commands from a directory.

        Args:
            commands_dir: Directory to search for TOML command files

        Returns:
            Dict mapping command names to SlashCommand objects
        """
        discovered: dict[str, SlashCommand] = {}

        if not commands_dir.exists() or not commands_dir.is_dir():
            return discovered

        # Find all .toml files recursively
        for toml_file in commands_dir.rglob("*.toml"):
            command = self._parse_command_file(toml_file, commands_dir)
            if command:
                discovered[command.name] = command

        return discovered

    def _parse_command_file(self, file_path: Path, base_dir: Path) -> SlashCommand | None:
        """
        Parse a TOML command file.

        The command name is derived from the file path relative to the base directory.
        Subdirectories are converted to namespaced commands with ':' separator.

        Args:
            file_path: Path to the .toml file
            base_dir: Base commands directory for name calculation

        Returns:
            SlashCommand if valid, None otherwise
        """
        try:
            content = file_path.read_bytes()
            data = tomllib.loads(content.decode("utf-8"))

            prompt = data.get("prompt")
            if not isinstance(prompt, str):
                return None

            # Calculate command name from path
            relative_path = file_path.relative_to(base_dir)
            name_parts = list(relative_path.parts)
            # Remove .toml extension from last part
            name_parts[-1] = name_parts[-1][:-5]  # len('.toml') == 5

            # Join with ':' for namespacing
            command_name = ":".join(name_parts)

            # Sanitize colons in individual parts
            command_name = command_name.replace("::", ":")

            description = data.get("description", f"Custom command from {file_path.name}")

            return SlashCommand(
                name=command_name,
                description=description if isinstance(description, str) else "",
                kind=CommandKind.FILE,
                source_file=str(file_path),
                prompt_template=prompt,
            )
        except Exception:
            return None

    def get_command(self, name: str) -> SlashCommand | None:
        """Get a command by name."""
        return self._commands.get(name)

    def get_all_commands(self) -> list[SlashCommand]:
        """Get all available commands."""
        return list(self._commands.values())

    def get_commands_matching(self, prefix: str) -> list[SlashCommand]:
        """Get commands matching a prefix (for autocomplete)."""
        return [cmd for name, cmd in self._commands.items() if name.startswith(prefix)]

    def parse_input(self, user_input: str) -> tuple[SlashCommand | None, str]:
        """
        Parse user input to detect and match a slash command.

        Args:
            user_input: The raw user input string

        Returns:
            Tuple of (matched command or None, remaining args)
        """
        trimmed = user_input.strip()

        if not trimmed.startswith("/"):
            return None, user_input

        # Remove leading slash
        without_slash = trimmed[1:]

        # Split into command and args
        parts = without_slash.split(maxsplit=1)
        command_str = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        # Try to find the command
        command = self.get_command(command_str)
        if command:
            return command, args

        # Try to find a partial match for nested commands
        # e.g., "/git commit message" should match "git:commit"
        for name, cmd in self._commands.items():
            # Check if the input starts with the command name (with spaces as separators)
            input_as_namespaced = command_str.replace(" ", ":")
            if input_as_namespaced == name or name.startswith(input_as_namespaced + ":"):
                return cmd, args

        # Handle wildcard skill commands: /skill:* matches /skill:deploy, /skill:heartbeat, etc.
        for name, cmd in self._commands.items():
            if name.endswith(":*"):
                prefix = name[:-1]  # Remove '*' but keep colon, e.g., "skill:"
                if command_str.startswith(prefix):
                    # Return the wildcard command with the actual command name
                    # The action handler will extract the skill name from command_name
                    actual_cmd = SlashCommand(
                        name=command_str,
                        description=cmd.description,
                        kind=cmd.kind,
                        action=cmd.action,
                        auto_execute=cmd.auto_execute,
                    )
                    return actual_cmd, args

        return None, user_input

    def execute_command(
        self,
        command: SlashCommand,
        args: str,
        work_dir: Path | None = None,
        project_root: Path | None = None,
    ) -> CommandResult:
        """
        Execute a slash command and return the result.

        Args:
            command: The command to execute
            args: Arguments to pass to the command
            work_dir: Current working directory
            project_root: Project root directory

        Returns:
            CommandResult with the outcome
        """
        context = CommandContext(
            raw_input=f"/{command.name} {args}",
            command_name=command.name,
            args=args,
            work_dir=work_dir,
            project_root=project_root,
        )

        if command.action:
            # Built-in or dynamic command with an action
            return command.action(context, args)

        if command.prompt_template:
            # File-based command with a prompt template
            prompt = self._process_template(command.prompt_template, context)
            return CommandResult(type="submit_prompt", content=prompt)

        return CommandResult(type="message", content=f"Command '{command.name}' has no action", message_type="error")

    def _process_template(self, template: str, context: CommandContext) -> str:
        """
        Process a prompt template with argument and injection substitution.

        Args:
            template: The prompt template string
            context: The command context with arguments

        Returns:
            The processed prompt string
        """
        result = template

        # Replace {{args}} placeholder
        if ARGS_PLACEHOLDER.search(result):
            result = ARGS_PLACEHOLDER.sub(context.args, result)
        else:
            # Default behavior: append args with two newlines if present
            if context.args.strip():
                result = f"{result}\n\n{context.raw_input}"

        # Process @{...} file injections
        result = self._process_file_injections(result, context)

        # Process !{...} shell injections
        result = self._process_shell_injections(result, context)

        return result

    def _process_file_injections(self, prompt: str, context: CommandContext) -> str:
        """Process @{path} file content injections."""

        def replace_file(match: re.Match) -> str:
            path_str = match.group(1).strip()

            # Resolve path relative to work_dir or project_root
            path = Path(path_str)
            if not path.is_absolute():
                if context.work_dir:
                    path = context.work_dir / path
                elif context.project_root:
                    path = context.project_root / path

            try:
                if path.is_file():
                    return path.read_text(encoding="utf-8")
                elif path.is_dir():
                    # List directory contents
                    files = list(path.rglob("*"))
                    return "\n".join(str(f.relative_to(path)) for f in files if f.is_file())
            except Exception as e:
                return f"[Error reading {path_str}: {e}]"

            return f"[File not found: {path_str}]"

        return FILE_INJECTION.sub(replace_file, prompt)

    def _process_shell_injections(self, prompt: str, context: CommandContext) -> str:
        """Process !{command} shell command injections."""

        def replace_shell(match: re.Match) -> str:
            shell_cmd = match.group(1).strip()

            # Replace {{args}} inside shell commands (with escaping)
            if "{{args}}" in shell_cmd:
                # Shell-escape the args
                escaped_args = self._shell_escape(context.args)
                shell_cmd = shell_cmd.replace("{{args}}", escaped_args)

            try:
                cwd = str(context.work_dir) if context.work_dir else None
                result = subprocess.run(
                    shell_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=cwd,
                )
                output = result.stdout or ""
                if result.returncode != 0:
                    if result.stderr:
                        output += f"\n{result.stderr}"
                    output += f"\n[Shell command exited with code {result.returncode}]"
                return output.strip()
            except subprocess.TimeoutExpired:
                return f"[Shell command timed out: {shell_cmd}]"
            except Exception as e:
                return f"[Error executing shell command: {e}]"

        return SHELL_INJECTION.sub(replace_shell, prompt)

    def _shell_escape(self, s: str) -> str:
        """Escape a string for safe use in shell commands."""
        import shlex

        return shlex.quote(s)


# Built-in commands registry
def _make_help_command(manager: CommandManager) -> SlashCommand:
    """Create the /help command."""

    def help_action(context: CommandContext, args: str) -> CommandResult:
        commands = manager.get_all_commands()
        if not commands:
            return CommandResult(type="message", content="No commands available.")

        lines = ["**Available Slash Commands:**\n"]
        for cmd in sorted(commands, key=lambda c: c.name):
            lines.append(f"- `/{cmd.name}`: {cmd.description}")

        return CommandResult(type="message", content="\n".join(lines))

    return SlashCommand(
        name="help",
        description="Show available slash commands",
        kind=CommandKind.BUILT_IN,
        action=help_action,
    )


def _make_clear_command() -> SlashCommand:
    """Create the /clear command."""

    def clear_action(context: CommandContext, args: str) -> CommandResult:
        return CommandResult(type="handled", content="clear")

    return SlashCommand(
        name="clear",
        description="Clear conversation history",
        kind=CommandKind.BUILT_IN,
        action=clear_action,
    )


def _make_exit_command() -> SlashCommand:
    """Create the /exit command."""

    def exit_action(context: CommandContext, args: str) -> CommandResult:
        return CommandResult(type="handled", content="exit")

    return SlashCommand(
        name="exit",
        description="Exit the chat session",
        kind=CommandKind.BUILT_IN,
        action=exit_action,
        auto_execute=True,
    )


def _make_info_command() -> SlashCommand:
    """Create the /info command."""

    def info_action(context: CommandContext, args: str) -> CommandResult:
        return CommandResult(type="handled", content="info")

    return SlashCommand(
        name="info",
        description="Show session information",
        kind=CommandKind.BUILT_IN,
        action=info_action,
    )


def _make_new_command() -> SlashCommand:
    """Create the /new command."""

    def new_action(context: CommandContext, args: str) -> CommandResult:
        return CommandResult(type="handled", content="new_session")

    return SlashCommand(
        name="new",
        description="Start a new conversation session",
        kind=CommandKind.BUILT_IN,
        action=new_action,
    )


def _make_session_command() -> SlashCommand:
    """Create the /session command."""

    def session_action(context: CommandContext, args: str) -> CommandResult:
        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else "list"
        value = parts[1].strip() if len(parts) > 1 else ""

        if subcommand == "list":
            return CommandResult(type="handled", content="session:list")
        if subcommand == "new":
            return CommandResult(type="handled", content="new_session")
        if subcommand == "switch" and value:
            return CommandResult(type="handled", content=f"session:switch {value}")
        return CommandResult(
            type="message",
            content="Usage: /session new|list|switch <id>",
            message_type="info",
        )

    return SlashCommand(
        name="session",
        description="Manage sessions: /session new|list|switch <id>",
        kind=CommandKind.BUILT_IN,
        action=session_action,
    )


def _make_cancel_command() -> SlashCommand:
    """Create the /cancel command."""

    def cancel_action(context: CommandContext, args: str) -> CommandResult:
        return CommandResult(type="handled", content="cancel")

    return SlashCommand(
        name="cancel",
        description="Cancel current operation",
        kind=CommandKind.BUILT_IN,
        action=cancel_action,
    )


def _make_skills_command(skill_manager) -> SlashCommand:
    """Create the /skills command."""

    def skills_action(context: CommandContext, args: str) -> CommandResult:
        from .skills import get_skill_manager

        sm = skill_manager or get_skill_manager()
        # Re-discover skills to pick up any newly created skills
        if context.work_dir:
            sm.discover_skills(context.work_dir)

        sub_args = args.strip().split(maxsplit=1)
        subcommand = sub_args[0].lower() if sub_args else "list"
        skill_arg = sub_args[1] if len(sub_args) > 1 else ""

        def _list_skills() -> CommandResult:
            skills = sm.get_all_skills()
            if not skills:
                return CommandResult(type="message", content="No skills found.")

            lines = ["**Available Skills:**\n"]
            for skill in skills:
                status = "🔴 (disabled)" if skill.disabled else "🟢"
                active = " ⭐" if sm.is_skill_active(skill.name) else ""
                auto_trigger = " 🤖" if skill.auto_trigger else " 🚫"
                lines.append(f"- {status} **{skill.name}**{active}{auto_trigger}: {skill.description}")
                if skill.parameters:
                    for param in skill.parameters:
                        req = " (required)" if param.required else ""
                        default = f" [default: {param.default}]" if param.default else ""
                        lines.append(f"    - param `{param.name}`{req}{default}: {param.description}")

            lines.append("\nLegend: ⭐ = active, 🤖 = auto-trigger, 🚫 = explicit-only")
            return CommandResult(type="message", content="\n".join(lines))

        def _activate_skill() -> CommandResult:
            if not skill_arg:
                return CommandResult(
                    type="message", content="Please provide a skill name to activate.", message_type="error"
                )
            if sm.activate_skill(skill_arg):
                return CommandResult(type="message", content=f"Skill '{skill_arg}' activated.", message_type="success")
            else:
                return CommandResult(
                    type="message", content=f"Skill '{skill_arg}' not found or disabled.", message_type="error"
                )

        def _deactivate_skill() -> CommandResult:
            if not skill_arg:
                return CommandResult(
                    type="message", content="Please provide a skill name to deactivate.", message_type="error"
                )
            sm.deactivate_skill(skill_arg)
            return CommandResult(type="message", content=f"Skill '{skill_arg}' deactivated.", message_type="success")

        def _show_skill() -> CommandResult:
            if not skill_arg:
                return CommandResult(
                    type="message", content="Please provide a skill name to show.", message_type="error"
                )
            skill = sm.get_skill(skill_arg)
            if skill:
                content = f"**Skill: {skill.name}**\n\n*{skill.description}*\n\n---\n\n{skill.body}"
                return CommandResult(type="message", content=content)
            else:
                return CommandResult(type="message", content=f"Skill '{skill_arg}' not found.", message_type="error")

        handlers: dict[str, Callable[[], CommandResult]] = {
            "list": _list_skills,
            "activate": _activate_skill,
            "deactivate": _deactivate_skill,
            "show": _show_skill,
        }

        if subcommand not in handlers:
            return CommandResult(
                type="message",
                content="Usage: /skills [list|activate <name>|deactivate <name>|show <name>]",
                message_type="info",
            )

        return handlers[subcommand]()

    return SlashCommand(
        name="skills",
        description="Manage agent skills: /skills [list|activate|deactivate|show]",
        kind=CommandKind.BUILT_IN,
        action=skills_action,
    )


def _make_activate_command(skill_manager) -> SlashCommand:
    """Create the /activate command as a shorthand for /skills activate."""

    def activate_action(context: CommandContext, args: str) -> CommandResult:
        from .skills import get_skill_manager

        name = args.strip()
        if not name:
            return CommandResult(type="message", content="Usage: /activate <skill>", message_type="info")

        sm = skill_manager or get_skill_manager()
        if context.work_dir:
            sm.discover_skills(context.work_dir)
        if sm.activate_skill(name):
            return CommandResult(type="message", content=f"Skill '{name}' activated.", message_type="success")
        return CommandResult(type="message", content=f"Skill '{name}' not found or disabled.", message_type="error")

    return SlashCommand(
        name="activate",
        description="Activate a skill: /activate <skill>",
        kind=CommandKind.BUILT_IN,
        action=activate_action,
    )


def _make_skill_command(skill_manager) -> SlashCommand:
    """Create the /skill:name command for explicit skill invocation.

    This command allows users to explicitly invoke a skill by name,
    optionally passing parameters. The skill's body is submitted as
    a prompt to the agent.

    Usage:
        /skill:<name> [param1=value1 param2=value2 ...]
        /skill:deploy env=production
        /skill:heartbeat
    """

    def skill_action(context: CommandContext, args: str) -> CommandResult:
        from .skills import get_skill_manager

        sm = skill_manager or get_skill_manager()
        if context.work_dir:
            sm.discover_skills(context.work_dir)

        # Extract skill name from command (e.g., "/skill:deploy" -> "deploy")
        command_name = context.command_name
        if command_name.startswith("skill:"):
            skill_name = command_name[6:]  # Remove "skill:" prefix
        else:
            return CommandResult(
                type="message",
                content=f"Invalid skill command: {command_name}",
                message_type="error",
            )

        skill = sm.get_skill(skill_name)
        if not skill:
            return CommandResult(
                type="message",
                content=f"Skill '{skill_name}' not found. Use /skills list to see available skills.",
                message_type="error",
            )

        if skill.disabled:
            return CommandResult(
                type="message",
                content=f"Skill '{skill_name}' is disabled. Enable it with /skills activate {skill_name}",
                message_type="error",
            )

        # Parse parameters from args (key=value format)
        params: dict[str, str] = {}
        remaining_args = args.strip()
        if remaining_args:
            # Parse key=value pairs
            param_pattern = re.compile(r'(\w+)=([^\s"\']+|"[^"]*"|\'[^\']*\')')
            for match in param_pattern.finditer(remaining_args):
                key = match.group(1)
                value = match.group(2).strip("\"'")
                params[key] = value

        # Build the prompt from skill body + parameters
        prompt_parts: list[str] = []
        prompt_parts.append(f"# Skill: {skill.name}")
        prompt_parts.append(f"*{skill.description}*")
        prompt_parts.append("")
        prompt_parts.append(skill.body)

        # Add parameter context if provided
        if params:
            prompt_parts.append("")
            prompt_parts.append("## Parameters")
            for key, value in params.items():
                prompt_parts.append(f"- {key}: {value}")

        # Validate required parameters
        if skill.parameters:
            missing = []
            for param in skill.parameters:
                if param.required and param.name not in params and param.default is None:
                    missing.append(param.name)
            if missing:
                return CommandResult(
                    type="message",
                    content=f"Missing required parameters for skill '{skill_name}': {', '.join(missing)}",
                    message_type="error",
                )

        # Auto-activate the skill when explicitly invoked
        sm.activate_skill(skill_name)

        return CommandResult(type="submit_prompt", content="\n".join(prompt_parts))

    return SlashCommand(
        name="skill:*",
        description="Invoke a skill by name: /skill:<name> [key=value ...]",
        kind=CommandKind.BUILT_IN,
        action=skill_action,
    )


def _make_profile_command(command_name: str, label: str, file_name: str) -> SlashCommand:
    """Create a built-in command for soul or identity management."""

    def profile_action(ctx: CommandContext, args: str) -> CommandResult:
        from .memory import get_memory_manager

        raw_args = args.strip()
        scope = "user"
        if raw_args == "project" or raw_args.startswith("project "):
            scope = "project"
            raw_args = raw_args[len("project") :].strip()

        action, _, content = raw_args.partition(" ")
        action = action or "show"
        content = content.strip()
        manager = get_memory_manager(ctx.project_root or ctx.work_dir)

        if action in {"show", "read"}:
            if command_name == "soul":
                value = manager.read_soul(scope, include_default=True)
            else:
                value = manager.read_identity(scope)
            if not value:
                return CommandResult(
                    type="message",
                    content=f"No {label.lower()} configured for {scope} scope.",
                )
            return CommandResult(type="message", content=value)

        if action in {"set", "write"}:
            if not content:
                return CommandResult(
                    type="message",
                    content=f"Usage: /{command_name} [project] set <{label.lower()} text>",
                    message_type="error",
                )
            if command_name == "soul":
                manager.write_soul(content, scope)
            else:
                manager.write_identity(content, scope)
            return CommandResult(
                type="message",
                content=f"{label} saved to {scope} scope ({file_name}).",
                message_type="success",
            )

        return CommandResult(
            type="message",
            content=f"Usage: /{command_name} [show|set <text>] or /{command_name} project set <text>",
            message_type="error",
        )

    return SlashCommand(
        name=command_name,
        description=f"Show or set durable {label.lower()} ({file_name})",
        kind=CommandKind.BUILT_IN,
        action=profile_action,
    )


# Global command manager instance
_command_manager: CommandManager | None = None


def get_command_manager() -> CommandManager:
    """Get or create the global command manager."""
    global _command_manager
    if _command_manager is None:
        _command_manager = CommandManager()
        _init_builtin_commands(_command_manager)
    return _command_manager


def _init_builtin_commands(manager: CommandManager) -> None:
    """Initialize built-in commands."""
    manager.register_builtin(_make_help_command(manager))
    manager.register_builtin(_make_clear_command())
    manager.register_builtin(_make_exit_command())
    manager.register_builtin(_make_info_command())
    manager.register_builtin(_make_new_command())
    manager.register_builtin(_make_session_command())
    manager.register_builtin(_make_cancel_command())
    manager.register_builtin(_make_skills_command(None))
    manager.register_builtin(_make_activate_command(None))
    manager.register_builtin(_make_skill_command(None))
    manager.register_builtin(_make_profile_command("soul", "Soul", "SOUL.md"))
    manager.register_builtin(_make_profile_command("identity", "Identity", "IDENTITY.md"))


def reset_command_manager() -> None:
    """Reset the global command manager (for testing)."""
    global _command_manager
    _command_manager = None
