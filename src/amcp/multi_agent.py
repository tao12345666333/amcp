"""
Multi-Agent System for AMCP.

This module provides support for multiple agents with different capabilities,
including Primary agents and Subagents with explicit mode differentiation.

Inspired by:
- OpenCode's agent modes (primary, subagent, explore, plan)
- Crush's Coordinator pattern with message queuing
- Kimi-CLI's LaborMarket for agent management

Features:
- AgentMode.PRIMARY / AgentMode.SUBAGENT differentiation
- Built-in agent configurations for common tasks
- Agent registry for dynamic agent lookup
- Support for agent delegation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class AgentMode(Enum):
    """Agent execution mode."""

    PRIMARY = "primary"
    """Primary agent with full capabilities - can delegate to subagents."""

    SUBAGENT = "subagent"
    """Subagent with restricted capabilities - focuses on single tasks."""


@dataclass
class AgentConfig:
    """Configuration for an agent type.

    Attributes:
        name: Unique identifier for the agent
        mode: PRIMARY for main agents, SUBAGENT for task-specific agents
        description: Human-readable description of agent's purpose
        system_prompt: System prompt template for the agent
        tools: List of tool names the agent can use
        excluded_tools: Tools explicitly disabled for this agent
        max_steps: Maximum execution steps for this agent
        can_delegate: Whether this agent can spawn subagents
        parent_agent: Name of parent agent (for subagents)
    """

    name: str
    mode: AgentMode
    description: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    excluded_tools: list[str] = field(default_factory=list)
    max_steps: int = 100
    can_delegate: bool = True
    parent_agent: str | None = None

    def __post_init__(self):
        """Validate agent configuration."""
        # Subagents cannot delegate by default
        if self.mode == AgentMode.SUBAGENT:
            self.can_delegate = False

    def get_effective_tools(self, available_tools: list[str]) -> list[str]:
        """Get the effective list of tools for this agent.

        Args:
            available_tools: All available tools in the system

        Returns:
            List of tool names this agent can use
        """
        # Use explicit whitelist or all available tools
        effective = [t for t in self.tools if t in available_tools] if self.tools else list(available_tools)

        # Apply exclusions
        return [t for t in effective if t not in self.excluded_tools]


# Default system prompt templates
PRIMARY_SYSTEM_PROMPT = """You are {agent_name}, an AI coding assistant with full capabilities.

You can use all available tools to help users with software engineering tasks.
When tasks are complex, you may delegate to specialized subagents.

Current working directory: {work_dir}
Current time: {current_time}

Guidelines:
- Use appropriate tools for each task
- Read files to understand the codebase before making changes
- Delegate complex sub-tasks to specialized agents when needed
- Be precise and efficient in your tool usage
- Explain your actions when helpful"""

EXPLORER_SYSTEM_PROMPT = """You are {agent_name}, a fast codebase exploration agent.

Your task is to quickly analyze and understand codebases WITHOUT making changes.
You have READ-ONLY access to files and search tools.

Current working directory: {work_dir}
Current time: {current_time}

Guidelines:
- Focus on quick exploration and understanding
- Do NOT attempt to modify any files
- Summarize your findings concisely
- Report back to the main agent when done"""

PLANNER_SYSTEM_PROMPT = """You are {agent_name}, a planning and analysis agent.

Your task is to analyze problems and create execution plans WITHOUT implementing them.
You have READ-ONLY access to the codebase.

Current working directory: {work_dir}
Current time: {current_time}

Guidelines:
- Create detailed, step-by-step plans
- Identify potential issues and edge cases
- Do NOT implement the plan yourself
- Return a clear, actionable plan to the main agent"""

CODER_SYSTEM_PROMPT = """You are {agent_name}, a focused coding agent.

Your task is to implement specific code changes as directed.
You have full write access to the codebase.

Current working directory: {work_dir}
Current time: {current_time}

Guidelines:
- Implement exactly what is requested
- Follow existing code patterns and style
- Test your changes when possible
- Keep changes minimal and focused"""

# Built-in agent configurations
BUILTIN_AGENTS: dict[str, AgentConfig] = {
    "coder": AgentConfig(
        name="coder",
        mode=AgentMode.PRIMARY,
        description="Main coding agent with full capabilities",
        system_prompt=PRIMARY_SYSTEM_PROMPT,
        tools=[],  # Empty means all available tools
        excluded_tools=[],
        max_steps=300,
        can_delegate=True,
    ),
    "explorer": AgentConfig(
        name="explorer",
        mode=AgentMode.SUBAGENT,
        description="Fast codebase exploration agent (read-only)",
        system_prompt=EXPLORER_SYSTEM_PROMPT,
        tools=["read_file", "grep", "glob", "think"],
        excluded_tools=["write_file", "edit_file", "bash"],
        max_steps=100,
        can_delegate=False,
    ),
    "planner": AgentConfig(
        name="planner",
        mode=AgentMode.SUBAGENT,
        description="Planning agent for analysis and strategy (read-only)",
        system_prompt=PLANNER_SYSTEM_PROMPT,
        tools=["read_file", "grep", "glob", "think"],
        excluded_tools=["write_file", "edit_file", "bash"],
        max_steps=150,
        can_delegate=False,
    ),
    "focused_coder": AgentConfig(
        name="focused_coder",
        mode=AgentMode.SUBAGENT,
        description="Focused coding agent for specific implementation tasks",
        system_prompt=CODER_SYSTEM_PROMPT,
        tools=["read_file", "grep", "write_file", "edit_file", "bash", "think"],
        excluded_tools=[],
        max_steps=200,
        can_delegate=False,
    ),
}


class AgentRegistry:
    """Registry for managing and looking up agent configurations.

    This class provides centralized management of agent configurations,
    supporting both built-in and custom agents.
    """

    def __init__(self):
        """Initialize the agent registry with built-in agents."""
        self._agents: dict[str, AgentConfig] = dict(BUILTIN_AGENTS)
        self._custom_agents: dict[str, AgentConfig] = {}

    def register(self, config: AgentConfig) -> None:
        """Register a custom agent configuration.

        Args:
            config: Agent configuration to register
        """
        self._custom_agents[config.name] = config
        self._agents[config.name] = config

    def get(self, name: str) -> AgentConfig | None:
        """Get an agent configuration by name.

        Args:
            name: Agent name

        Returns:
            Agent configuration or None if not found
        """
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        """List all registered agent names.

        Returns:
            List of agent names
        """
        return list(self._agents.keys())

    def list_primary_agents(self) -> list[str]:
        """List all primary agent names.

        Returns:
            List of primary agent names
        """
        return [name for name, cfg in self._agents.items() if cfg.mode == AgentMode.PRIMARY]

    def list_subagents(self) -> list[str]:
        """List all subagent names.

        Returns:
            List of subagent names
        """
        return [name for name, cfg in self._agents.items() if cfg.mode == AgentMode.SUBAGENT]

    def get_subagents_for(self, parent_name: str) -> list[str]:
        """Get subagents that can be used by a parent agent.

        Args:
            parent_name: Name of the parent agent

        Returns:
            List of subagent names available to the parent
        """
        parent = self.get(parent_name)
        if not parent or not parent.can_delegate:
            return []

        return self.list_subagents()

    def load_from_file(self, config_file: Path) -> None:
        """Load agent configurations from a YAML file.

        Args:
            config_file: Path to YAML configuration file
        """
        import yaml

        if not config_file.exists():
            return

        try:
            with open(config_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or "agents" not in data:
                return

            for agent_data in data.get("agents", []):
                # Parse mode
                mode_str = agent_data.get("mode", "primary")
                mode = AgentMode.PRIMARY if mode_str == "primary" else AgentMode.SUBAGENT

                config = AgentConfig(
                    name=agent_data.get("name", "custom"),
                    mode=mode,
                    description=agent_data.get("description", ""),
                    system_prompt=agent_data.get("system_prompt", PRIMARY_SYSTEM_PROMPT),
                    tools=agent_data.get("tools", []),
                    excluded_tools=agent_data.get("excluded_tools", []),
                    max_steps=agent_data.get("max_steps", 100),
                    can_delegate=agent_data.get("can_delegate", mode == AgentMode.PRIMARY),
                    parent_agent=agent_data.get("parent_agent"),
                )
                self.register(config)

        except Exception as e:
            # Log but don't fail
            print(f"Warning: Could not load agent config file: {e}")


# Global agent registry singleton
_agent_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry.

    Returns:
        Global AgentRegistry instance
    """
    global _agent_registry
    if _agent_registry is None:
        _agent_registry = AgentRegistry()
    return _agent_registry


def get_agent_config(name: str) -> AgentConfig | None:
    """Get an agent configuration by name.

    Args:
        name: Agent name

    Returns:
        Agent configuration or None if not found
    """
    return get_agent_registry().get(name)


def create_subagent_config(
    parent_name: str,
    task_description: str,
    tools: list[str] | None = None,
) -> AgentConfig:
    """Create a dynamic subagent configuration for a specific task.

    This is used for creating task-specific agents at runtime.

    Args:
        parent_name: Name of the parent agent
        task_description: Description of the task for the subagent
        tools: Optional list of tools for the subagent

    Returns:
        New AgentConfig for the subagent
    """
    import uuid

    subagent_id = str(uuid.uuid4())[:8]
    subagent_name = f"task_{subagent_id}"

    system_prompt = f"""You are a specialized task agent for: {task_description}

Complete this specific task and report back when done.
Be focused and efficient in completing the assigned task.

Current working directory: {{work_dir}}
Current time: {{current_time}}

Task: {task_description}
"""

    return AgentConfig(
        name=subagent_name,
        mode=AgentMode.SUBAGENT,
        description=task_description,
        system_prompt=system_prompt,
        tools=tools or ["read_file", "grep", "write_file", "edit_file", "think"],
        excluded_tools=[],
        max_steps=50,
        can_delegate=False,
        parent_agent=parent_name,
    )
