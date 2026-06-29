"""Transport-neutral interaction routing for AMCP chat surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .commands import CommandManager, get_command_manager

InteractionAction = Literal[
    "prompt",
    "message",
    "new_session",
    "session_list",
    "session_switch",
    "clear",
    "info",
    "exit",
    "cancel",
]


@dataclass
class InteractionResult:
    """Result of routing a user message before agent execution."""

    action: InteractionAction
    content: str = ""
    message_type: str = "info"
    session_id: str | None = None


def route_interaction(
    user_input: str,
    *,
    work_dir: Path | None = None,
    project_root: Path | None = None,
    command_manager: CommandManager | None = None,
    discover_commands: bool = True,
) -> InteractionResult:
    """Route a message through shared slash-command handling.

    Non-command messages and slash commands that expand to prompts return
    ``action="prompt"`` with the prompt content to submit to the agent.
    """
    if not user_input.strip().startswith("/"):
        return InteractionResult(action="prompt", content=user_input)

    manager = command_manager or get_command_manager()
    if discover_commands:
        manager.discover_commands(project_root or work_dir)

    command, args = manager.parse_input(user_input)
    if command is None:
        return InteractionResult(
            action="message",
            content=f"Unknown command: {user_input}\nUse /help to see available commands.",
            message_type="error",
        )

    result = manager.execute_command(command, args, work_dir=work_dir, project_root=project_root)
    if result.type == "submit_prompt":
        return InteractionResult(action="prompt", content=result.content)
    if result.type == "message":
        return InteractionResult(
            action="message",
            content=result.content,
            message_type=result.message_type,
        )
    if result.type == "handled":
        return _handled_result(result.content)

    return InteractionResult(action="message", content=result.content, message_type=result.message_type)


def _handled_result(content: str) -> InteractionResult:
    if content == "new_session":
        return InteractionResult(action="new_session")
    if content == "session:list":
        return InteractionResult(action="session_list")
    if content.startswith("session:switch "):
        session_id = content.removeprefix("session:switch ").strip()
        return InteractionResult(action="session_switch", session_id=session_id)
    if content in {"clear", "info", "exit", "cancel"}:
        return InteractionResult(action=content)  # type: ignore[arg-type]
    return InteractionResult(action="message", content=content)
