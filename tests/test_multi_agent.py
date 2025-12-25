"""Tests for the multi_agent module."""

import pytest

from amcp.multi_agent import (
    AgentConfig,
    AgentMode,
    AgentRegistry,
    BUILTIN_AGENTS,
    PRIMARY_SYSTEM_PROMPT,
    create_subagent_config,
    get_agent_config,
    get_agent_registry,
)


class TestAgentMode:
    """Tests for AgentMode enum."""

    def test_mode_values(self):
        """Test that mode values are correct."""
        assert AgentMode.PRIMARY.value == "primary"
        assert AgentMode.SUBAGENT.value == "subagent"

    def test_mode_comparison(self):
        """Test mode comparison."""
        assert AgentMode.PRIMARY != AgentMode.SUBAGENT
        assert AgentMode.PRIMARY == AgentMode.PRIMARY


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_basic_creation(self):
        """Test basic AgentConfig creation."""
        config = AgentConfig(
            name="test_agent",
            mode=AgentMode.PRIMARY,
            description="Test agent",
            system_prompt="You are a test agent.",
        )
        assert config.name == "test_agent"
        assert config.mode == AgentMode.PRIMARY
        assert config.description == "Test agent"
        assert config.can_delegate is True  # Default for PRIMARY

    def test_subagent_cannot_delegate(self):
        """Test that subagents have can_delegate set to False by __post_init__."""
        config = AgentConfig(
            name="test_subagent",
            mode=AgentMode.SUBAGENT,
            description="Test subagent",
            system_prompt="You are a test subagent.",
            can_delegate=True,  # This should be overridden
        )
        # __post_init__ should set can_delegate to False for subagents
        assert config.can_delegate is False

    def test_default_values(self):
        """Test default values are set correctly."""
        config = AgentConfig(
            name="test",
            mode=AgentMode.PRIMARY,
            description="Test",
            system_prompt="Test prompt",
        )
        assert config.tools == []
        assert config.excluded_tools == []
        assert config.max_steps == 100
        assert config.parent_agent is None

    def test_get_effective_tools_with_whitelist(self):
        """Test get_effective_tools with explicit tool whitelist."""
        config = AgentConfig(
            name="test",
            mode=AgentMode.SUBAGENT,
            description="Test",
            system_prompt="Test",
            tools=["read_file", "grep"],
        )
        available = ["read_file", "grep", "bash", "write_file"]
        effective = config.get_effective_tools(available)
        assert effective == ["read_file", "grep"]

    def test_get_effective_tools_with_exclusions(self):
        """Test get_effective_tools with tool exclusions."""
        config = AgentConfig(
            name="test",
            mode=AgentMode.PRIMARY,
            description="Test",
            system_prompt="Test",
            tools=[],  # Empty means all
            excluded_tools=["bash", "write_file"],
        )
        available = ["read_file", "grep", "bash", "write_file"]
        effective = config.get_effective_tools(available)
        assert "read_file" in effective
        assert "grep" in effective
        assert "bash" not in effective
        assert "write_file" not in effective

    def test_get_effective_tools_whitelist_and_exclusions(self):
        """Test get_effective_tools with both whitelist and exclusions."""
        config = AgentConfig(
            name="test",
            mode=AgentMode.SUBAGENT,
            description="Test",
            system_prompt="Test",
            tools=["read_file", "grep", "bash"],
            excluded_tools=["bash"],
        )
        available = ["read_file", "grep", "bash", "write_file"]
        effective = config.get_effective_tools(available)
        assert effective == ["read_file", "grep"]


class TestBuiltinAgents:
    """Tests for built-in agent configurations."""

    def test_coder_agent(self):
        """Test coder agent configuration."""
        assert "coder" in BUILTIN_AGENTS
        coder = BUILTIN_AGENTS["coder"]
        assert coder.mode == AgentMode.PRIMARY
        assert coder.can_delegate is True
        assert coder.max_steps == 300
        assert coder.tools == []  # All tools available

    def test_explorer_agent(self):
        """Test explorer agent configuration."""
        assert "explorer" in BUILTIN_AGENTS
        explorer = BUILTIN_AGENTS["explorer"]
        assert explorer.mode == AgentMode.SUBAGENT
        assert explorer.can_delegate is False
        assert "read_file" in explorer.tools
        assert "grep" in explorer.tools
        assert "write_file" in explorer.excluded_tools
        assert "edit_file" in explorer.excluded_tools
        assert "bash" in explorer.excluded_tools

    def test_planner_agent(self):
        """Test planner agent configuration."""
        assert "planner" in BUILTIN_AGENTS
        planner = BUILTIN_AGENTS["planner"]
        assert planner.mode == AgentMode.SUBAGENT
        assert planner.can_delegate is False
        assert planner.max_steps == 150

    def test_focused_coder_agent(self):
        """Test focused_coder agent configuration."""
        assert "focused_coder" in BUILTIN_AGENTS
        focused = BUILTIN_AGENTS["focused_coder"]
        assert focused.mode == AgentMode.SUBAGENT
        assert "write_file" in focused.tools
        assert "edit_file" in focused.tools
        assert "bash" in focused.tools


class TestAgentRegistry:
    """Tests for AgentRegistry."""

    def test_init_with_builtin_agents(self):
        """Test registry is initialized with built-in agents."""
        registry = AgentRegistry()
        assert "coder" in registry.list_agents()
        assert "explorer" in registry.list_agents()
        assert "planner" in registry.list_agents()
        assert "focused_coder" in registry.list_agents()

    def test_register_custom_agent(self):
        """Test registering a custom agent."""
        registry = AgentRegistry()
        custom = AgentConfig(
            name="custom_agent",
            mode=AgentMode.PRIMARY,
            description="Custom test agent",
            system_prompt="Custom prompt",
        )
        registry.register(custom)
        assert "custom_agent" in registry.list_agents()
        assert registry.get("custom_agent") == custom

    def test_get_nonexistent_agent(self):
        """Test getting a non-existent agent returns None."""
        registry = AgentRegistry()
        assert registry.get("nonexistent") is None

    def test_list_primary_agents(self):
        """Test listing primary agents."""
        registry = AgentRegistry()
        primary = registry.list_primary_agents()
        assert "coder" in primary
        assert "explorer" not in primary
        assert "planner" not in primary

    def test_list_subagents(self):
        """Test listing subagents."""
        registry = AgentRegistry()
        subagents = registry.list_subagents()
        assert "explorer" in subagents
        assert "planner" in subagents
        assert "focused_coder" in subagents
        assert "coder" not in subagents

    def test_get_subagents_for_delegating_agent(self):
        """Test getting subagents for an agent that can delegate."""
        registry = AgentRegistry()
        subagents = registry.get_subagents_for("coder")
        assert len(subagents) > 0
        assert "explorer" in subagents

    def test_get_subagents_for_non_delegating_agent(self):
        """Test getting subagents for an agent that cannot delegate."""
        registry = AgentRegistry()
        subagents = registry.get_subagents_for("explorer")
        assert subagents == []


class TestGlobalFunctions:
    """Tests for global helper functions."""

    def test_get_agent_registry_singleton(self):
        """Test that get_agent_registry returns a singleton."""
        registry1 = get_agent_registry()
        registry2 = get_agent_registry()
        assert registry1 is registry2

    def test_get_agent_config(self):
        """Test get_agent_config helper."""
        config = get_agent_config("coder")
        assert config is not None
        assert config.name == "coder"

    def test_get_agent_config_nonexistent(self):
        """Test get_agent_config returns None for non-existent agent."""
        config = get_agent_config("nonexistent")
        assert config is None


class TestCreateSubagentConfig:
    """Tests for create_subagent_config function."""

    def test_creates_unique_name(self):
        """Test that subagent config has a unique name."""
        config1 = create_subagent_config("coder", "Task 1")
        config2 = create_subagent_config("coder", "Task 2")
        assert config1.name != config2.name
        assert config1.name.startswith("task_")
        assert config2.name.startswith("task_")

    def test_sets_correct_mode(self):
        """Test that subagent config has SUBAGENT mode."""
        config = create_subagent_config("coder", "Test task")
        assert config.mode == AgentMode.SUBAGENT

    def test_sets_parent_agent(self):
        """Test that parent agent is set correctly."""
        config = create_subagent_config("coder", "Test task")
        assert config.parent_agent == "coder"

    def test_cannot_delegate(self):
        """Test that subagent cannot delegate."""
        config = create_subagent_config("coder", "Test task")
        assert config.can_delegate is False

    def test_custom_tools(self):
        """Test custom tools can be specified."""
        config = create_subagent_config(
            "coder",
            "Test task",
            tools=["read_file", "grep"],
        )
        assert config.tools == ["read_file", "grep"]

    def test_task_description_in_prompt(self):
        """Test task description is included in system prompt."""
        config = create_subagent_config("coder", "Analyze the codebase")
        assert "Analyze the codebase" in config.system_prompt


class TestSystemPromptTemplates:
    """Tests for system prompt templates."""

    def test_primary_system_prompt_has_placeholders(self):
        """Test that PRIMARY prompt has expected placeholders."""
        assert "{agent_name}" in PRIMARY_SYSTEM_PROMPT
        assert "{work_dir}" in PRIMARY_SYSTEM_PROMPT
        assert "{current_time}" in PRIMARY_SYSTEM_PROMPT
