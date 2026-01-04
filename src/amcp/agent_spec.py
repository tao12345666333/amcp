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
    max_steps: int = Field(default=20, description="Maximum tool execution steps")
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


def get_default_agent_spec(
    working_dir: str | None = None,
    model_name: str = "",
    available_tools: list[str] | None = None,
    skills_xml: str = "",
    memory_files: list[dict[str, str]] | None = None,
) -> ResolvedAgentSpec:
    """Get default agent specification with template-based system prompt.

    Args:
        working_dir: Current working directory
        model_name: Model name for prompt optimization
        available_tools: List of available tool names
        skills_xml: XML representation of available skills
        memory_files: List of memory file dicts with path and content

    Returns:
        ResolvedAgentSpec with rendered system prompt
    """
    from .prompts import PromptContext, get_prompt_manager

    # Create context from environment
    context = PromptContext.from_environment(
        working_dir=working_dir,
        model_name=model_name,
        available_tools=available_tools,
        skills_xml=skills_xml,
        memory_files=memory_files,
    )

    # Get rendered system prompt from template
    prompt_manager = get_prompt_manager()
    system_prompt = prompt_manager.get_system_prompt(context, template_name="coder")

    return ResolvedAgentSpec(
        name="default",
        description="Default AMCP agent with template-based prompts",
        mode=AgentMode.PRIMARY,
        system_prompt=system_prompt,
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


def get_subagent_spec(
    template_name: str,
    working_dir: str | None = None,
    model_name: str = "",
    available_tools: list[str] | None = None,
) -> ResolvedAgentSpec:
    """Get a subagent specification with a specific template.

    Args:
        template_name: Name of the template (explorer, planner, etc.)
        working_dir: Current working directory
        model_name: Model name for prompt optimization
        available_tools: List of available tool names

    Returns:
        ResolvedAgentSpec for the subagent
    """
    from .prompts import PromptContext, get_prompt_manager

    context = PromptContext.from_environment(
        working_dir=working_dir,
        model_name=model_name,
        available_tools=available_tools,
    )

    prompt_manager = get_prompt_manager()
    system_prompt = prompt_manager.get_system_prompt(context, template_name=template_name)

    return ResolvedAgentSpec(
        name=template_name,
        description=f"AMCP {template_name} subagent",
        mode=AgentMode.SUBAGENT,
        system_prompt=system_prompt,
        tools=available_tools or [],
        exclude_tools=[],
        max_steps=50,
        model="",
        base_url="",
        can_delegate=False,
    )


def list_available_templates() -> list[str]:
    """List all available prompt templates.

    Returns:
        List of template names (without extension)
    """
    from .prompts import get_prompt_manager

    pm = get_prompt_manager()
    templates = []

    if pm.templates_dir.exists():
        for f in pm.templates_dir.iterdir():
            if f.is_file() and f.suffix in [".md", ".txt"]:
                name = f.stem
                # Remove .md from .md.tpl files
                if name.endswith(".md"):
                    name = name[:-3]
                templates.append(name)

    return sorted(set(templates))
