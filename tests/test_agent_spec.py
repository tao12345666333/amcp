"""Tests for the agent_spec module."""

import pytest
from pathlib import Path

from amcp.agent_spec import (
    AgentSpec,
    AgentSpecError,
    ResolvedAgentSpec,
    get_default_agent_spec,
    load_agent_spec,
    list_available_agents,
)
from amcp.multi_agent import AgentMode


class TestGetDefaultAgentSpec:
    """Tests for get_default_agent_spec function."""

    def test_returns_resolved_spec(self):
        """Test that get_default_agent_spec returns a ResolvedAgentSpec."""
        spec = get_default_agent_spec()
        assert isinstance(spec, ResolvedAgentSpec)

    def test_default_name(self):
        """Test default agent name."""
        spec = get_default_agent_spec()
        assert spec.name == "default"

    def test_default_description(self):
        """Test default agent description."""
        spec = get_default_agent_spec()
        assert spec.description == "Default AMCP agent"

    def test_default_mode_is_primary(self):
        """Test that default agent is PRIMARY mode."""
        spec = get_default_agent_spec()
        assert spec.mode == AgentMode.PRIMARY

    def test_default_can_delegate(self):
        """Test that default agent can delegate."""
        spec = get_default_agent_spec()
        assert spec.can_delegate is True

    def test_has_system_prompt(self):
        """Test that default agent has a system prompt."""
        spec = get_default_agent_spec()
        assert len(spec.system_prompt) > 0
        assert "{work_dir}" in spec.system_prompt
        assert "{current_time}" in spec.system_prompt

    def test_default_max_steps(self):
        """Test default max_steps value."""
        spec = get_default_agent_spec()
        assert spec.max_steps == 300


class TestAgentSpec:
    """Tests for AgentSpec Pydantic model."""

    def test_minimal_spec(self):
        """Test creating a minimal agent spec."""
        spec = AgentSpec(
            name="test",
            system_prompt="You are a test agent.",
        )
        assert spec.name == "test"
        assert spec.mode == "primary"  # Default
        assert spec.can_delegate is True  # Default

    def test_spec_with_mode(self):
        """Test creating spec with explicit mode."""
        spec = AgentSpec(
            name="test",
            system_prompt="Test",
            mode="subagent",
        )
        assert spec.mode == "subagent"

    def test_spec_with_can_delegate(self):
        """Test creating spec with can_delegate."""
        spec = AgentSpec(
            name="test",
            system_prompt="Test",
            can_delegate=False,
        )
        assert spec.can_delegate is False

    def test_default_values(self):
        """Test default values."""
        spec = AgentSpec(
            name="test",
            system_prompt="Test",
        )
        assert spec.description == ""
        assert spec.tools == []
        assert spec.exclude_tools == []
        assert spec.max_steps == 5
        assert spec.model == ""
        assert spec.base_url == ""


class TestLoadAgentSpec:
    """Tests for load_agent_spec function."""

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading a non-existent file raises error."""
        with pytest.raises(AgentSpecError, match="not found"):
            load_agent_spec(tmp_path / "nonexistent.yaml")

    def test_load_empty_file(self, tmp_path):
        """Test loading an empty file raises error."""
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")

        with pytest.raises(AgentSpecError, match="Empty"):
            load_agent_spec(empty_file)

    def test_load_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML raises error."""
        invalid_file = tmp_path / "invalid.yaml"
        invalid_file.write_text("name: [invalid")

        with pytest.raises(AgentSpecError, match="Invalid YAML"):
            load_agent_spec(invalid_file)

    def test_load_valid_spec(self, tmp_path):
        """Test loading a valid agent spec."""
        spec_file = tmp_path / "agent.yaml"
        spec_file.write_text("""
name: test_agent
description: A test agent
mode: primary
system_prompt: You are a test agent.
tools:
  - read_file
  - grep
max_steps: 50
can_delegate: true
""")
        spec = load_agent_spec(spec_file)
        assert spec.name == "test_agent"
        assert spec.description == "A test agent"
        assert spec.mode == AgentMode.PRIMARY
        assert "read_file" in spec.tools
        assert spec.max_steps == 50
        assert spec.can_delegate is True

    def test_load_subagent_spec(self, tmp_path):
        """Test loading a subagent spec sets can_delegate to False."""
        spec_file = tmp_path / "subagent.yaml"
        spec_file.write_text("""
name: test_subagent
mode: subagent
system_prompt: You are a test subagent.
can_delegate: true  # This should be overridden
""")
        spec = load_agent_spec(spec_file)
        assert spec.mode == AgentMode.SUBAGENT
        assert spec.can_delegate is False  # Should be overridden

    def test_load_spec_with_template(self, tmp_path):
        """Test loading spec with system prompt template."""
        spec_file = tmp_path / "template.yaml"
        spec_file.write_text("""
name: template_agent
system_prompt: ""
system_prompt_template: "Hello, {name}! You work in {location}."
system_prompt_vars:
  name: TestBot
  location: TestLand
""")
        spec = load_agent_spec(spec_file)
        assert "Hello, TestBot!" in spec.system_prompt
        assert "TestLand" in spec.system_prompt


class TestListAvailableAgents:
    """Tests for list_available_agents function."""

    def test_empty_directory(self, tmp_path):
        """Test listing agents in empty directory."""
        agents = list_available_agents(tmp_path)
        assert agents == []

    def test_nonexistent_directory(self, tmp_path):
        """Test listing agents in non-existent directory."""
        agents = list_available_agents(tmp_path / "nonexistent")
        assert agents == []

    def test_finds_yaml_files(self, tmp_path):
        """Test that YAML files are found."""
        (tmp_path / "agent1.yaml").write_text("name: agent1\nsystem_prompt: test")
        (tmp_path / "agent2.yaml").write_text("name: agent2\nsystem_prompt: test")
        (tmp_path / "not_yaml.txt").write_text("not yaml")

        agents = list_available_agents(tmp_path)
        assert len(agents) == 2
        assert any(a.name == "agent1.yaml" for a in agents)
        assert any(a.name == "agent2.yaml" for a in agents)

    def test_finds_nested_yaml_files(self, tmp_path):
        """Test that nested YAML files are found."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.yaml").write_text("name: nested\nsystem_prompt: test")

        agents = list_available_agents(tmp_path)
        assert len(agents) == 1
        assert "nested.yaml" in str(agents[0])


class TestResolvedAgentSpec:
    """Tests for ResolvedAgentSpec dataclass."""

    def test_all_fields(self):
        """Test creating with all fields."""
        spec = ResolvedAgentSpec(
            name="test",
            description="Test description",
            mode=AgentMode.PRIMARY,
            system_prompt="Test prompt",
            tools=["read_file"],
            exclude_tools=["bash"],
            max_steps=100,
            model="test-model",
            base_url="https://test.api",
            can_delegate=True,
        )
        assert spec.name == "test"
        assert spec.mode == AgentMode.PRIMARY
        assert spec.can_delegate is True

    def test_default_can_delegate(self):
        """Test that can_delegate defaults to True."""
        spec = ResolvedAgentSpec(
            name="test",
            description="",
            mode=AgentMode.PRIMARY,
            system_prompt="",
            tools=[],
            exclude_tools=[],
            max_steps=100,
            model="",
            base_url="",
        )
        assert spec.can_delegate is True
