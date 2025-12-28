from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .config import load_config as load_app_config
from .multi_agent import AgentMode


class AgentSpecError(Exception):
    """Raised when agent specification is invalid."""

    pass


class AgentSpec(BaseModel):
    """Agent specification model."""

    name: str = Field(description="Agent name")
    description: str = Field(default="", description="Agent description")
    mode: str = Field(default="primary", description="Agent mode: 'primary' or 'subagent'")
    system_prompt: str = Field(description="System prompt for the agent")
    system_prompt_template: str = Field(default="", description="System prompt template with variables")
    system_prompt_vars: dict[str, str] = Field(default_factory=dict, description="Variables for system prompt template")
    tools: list[str] = Field(default_factory=list, description="Available tools")
    exclude_tools: list[str] = Field(default_factory=list, description="Tools to exclude")
    max_steps: int = Field(default=5, description="Maximum tool execution steps")
    model: str = Field(default="", description="Preferred model name")
    base_url: str = Field(default="", description="Preferred base URL")
    can_delegate: bool = Field(default=True, description="Whether agent can spawn subagents")

    class Config:
        extra = "allow"


@dataclass
class ResolvedAgentSpec:
    """Resolved agent specification with all defaults applied."""

    name: str
    description: str
    mode: AgentMode
    system_prompt: str
    tools: list[str]
    exclude_tools: list[str]
    max_steps: int
    model: str
    base_url: str
    can_delegate: bool = True


def load_agent_spec(agent_file: Path) -> ResolvedAgentSpec:
    """
    Load agent specification from YAML file.

    Args:
        agent_file: Path to agent specification file

    Returns:
        Resolved agent specification

    Raises:
        AgentSpecError: If file is invalid or cannot be loaded
    """
    if not agent_file.exists():
        raise AgentSpecError(f"Agent spec file not found: {agent_file}")

    try:
        with open(agent_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise AgentSpecError(f"Invalid YAML in agent spec file: {e}") from e

    if not data:
        raise AgentSpecError(f"Empty agent spec file: {agent_file}")

    try:
        spec = AgentSpec(**data)
    except Exception as e:
        raise AgentSpecError(f"Invalid agent spec format: {e}") from e

    # Apply defaults from global config
    cfg = load_app_config()
    default_model = cfg.chat.model if cfg.chat and cfg.chat.model else ""
    default_base_url = cfg.chat.base_url if cfg.chat and cfg.chat.base_url else ""

    # Resolve system prompt
    system_prompt = spec.system_prompt
    if spec.system_prompt_template and spec.system_prompt_vars:
        system_prompt = spec.system_prompt_template.format(**spec.system_prompt_vars)
    elif spec.system_prompt_template:
        system_prompt = spec.system_prompt_template

    # Parse mode
    mode = AgentMode.PRIMARY if spec.mode == "primary" else AgentMode.SUBAGENT

    # Subagents cannot delegate by default
    can_delegate = spec.can_delegate
    if mode == AgentMode.SUBAGENT:
        can_delegate = False

    return ResolvedAgentSpec(
        name=spec.name,
        description=spec.description,
        mode=mode,
        system_prompt=system_prompt,
        tools=spec.tools or [],
        exclude_tools=spec.exclude_tools or [],
        max_steps=spec.max_steps,
        model=spec.model or default_model,
        base_url=spec.base_url or default_base_url,
        can_delegate=can_delegate,
    )


def get_default_agent_spec() -> ResolvedAgentSpec:
    """Get default agent specification."""
    return ResolvedAgentSpec(
        name="default",
        description="Default AMCP agent",
        mode=AgentMode.PRIMARY,
        system_prompt="""You are AMCP, a Lego-style coding agent CLI. You help users with software engineering tasks using the available tools.

Available tools:
- read_file: Read text files from the workspace
- grep: Search for patterns in files using ripgrep
- bash: Execute bash commands for file operations and system tasks
- think: Internal reasoning and planning

Guidelines:
- Use appropriate tools for each task
- Read files to understand the codebase before making changes
- Use bash for file creation, editing, and system operations
- Use grep to search for code patterns
- Be precise and efficient in your tool usage
- Explain your actions when helpful

Current working directory: {work_dir}
Current time: {current_time}""",
        tools=[],
        exclude_tools=[],
        max_steps=1000,
        model="",
        base_url="",
        can_delegate=True,
    )


def list_available_agents(agents_dir: Path) -> list[Path]:
    """List all available agent specification files."""
    if not agents_dir.exists():
        return []

    agent_files = []
    for file_path in agents_dir.rglob("*.yaml"):
        if file_path.is_file():
            agent_files.append(file_path)

    return sorted(agent_files)
