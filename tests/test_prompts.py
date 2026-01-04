"""Tests for the prompts module."""

import os
import tempfile
from pathlib import Path

import pytest

from amcp.prompts import PromptContext, PromptManager, get_prompt_manager
from amcp.prompts.manager import ModelFamily


class TestModelFamily:
    """Tests for ModelFamily enum and detection."""

    def test_anthropic_detection(self):
        """Test Claude model detection."""
        ctx = PromptContext.from_environment(model_name="claude-sonnet-4-20250514")
        assert ctx.model_family == ModelFamily.ANTHROPIC

        ctx = PromptContext.from_environment(model_name="claude-3-opus")
        assert ctx.model_family == ModelFamily.ANTHROPIC

    def test_openai_detection(self):
        """Test GPT model detection."""
        ctx = PromptContext.from_environment(model_name="gpt-4o")
        assert ctx.model_family == ModelFamily.OPENAI

        ctx = PromptContext.from_environment(model_name="o1-preview")
        assert ctx.model_family == ModelFamily.OPENAI

    def test_gemini_detection(self):
        """Test Gemini model detection."""
        ctx = PromptContext.from_environment(model_name="gemini-2.0-flash")
        assert ctx.model_family == ModelFamily.GEMINI

    def test_qwen_detection(self):
        """Test Qwen model detection."""
        ctx = PromptContext.from_environment(model_name="qwen-2.5-coder")
        assert ctx.model_family == ModelFamily.QWEN

    def test_deepseek_detection(self):
        """Test DeepSeek model detection."""
        ctx = PromptContext.from_environment(model_name="deepseek-coder-v2")
        assert ctx.model_family == ModelFamily.DEEPSEEK

    def test_default_fallback(self):
        """Test unknown model falls back to default."""
        ctx = PromptContext.from_environment(model_name="unknown-model")
        assert ctx.model_family == ModelFamily.DEFAULT


class TestPromptContext:
    """Tests for PromptContext dataclass."""

    def test_from_environment(self):
        """Test creating context from environment."""
        ctx = PromptContext.from_environment(
            working_dir="/tmp/test",
            model_name="gpt-4o",
            available_tools=["read_file", "grep"],
        )
        assert ctx.working_dir == "/tmp/test"
        assert ctx.model_family == ModelFamily.OPENAI
        assert "read_file" in ctx.available_tools
        assert len(ctx.date) > 0
        assert len(ctx.time) > 0

    def test_git_info_detection(self):
        """Test git info detection in git repo."""
        # Use the AMCP repo itself for testing
        ctx = PromptContext.from_environment(
            working_dir=str(Path(__file__).parent.parent)
        )
        assert ctx.is_git_repo is True
        # Branch should be detected
        assert len(ctx.git_branch) > 0 or ctx.git_status != ""

    def test_non_git_directory(self):
        """Test non-git directory detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = PromptContext.from_environment(working_dir=tmpdir)
            assert ctx.is_git_repo is False
            assert ctx.git_branch == ""
            assert ctx.git_status == ""

    def test_skills_xml(self):
        """Test skills XML is included."""
        skills_xml = "<skills><skill>test</skill></skills>"
        ctx = PromptContext.from_environment(skills_xml=skills_xml)
        assert ctx.skills_xml == skills_xml

    def test_memory_files(self):
        """Test memory files are included."""
        memory = [{"path": "/test/file.md", "content": "test content"}]
        ctx = PromptContext.from_environment(memory_files=memory)
        assert len(ctx.memory_files) == 1
        assert ctx.memory_files[0]["path"] == "/test/file.md"


class TestPromptManager:
    """Tests for PromptManager class."""

    def test_get_prompt_manager_singleton(self):
        """Test that get_prompt_manager returns same instance."""
        pm1 = get_prompt_manager()
        pm2 = get_prompt_manager()
        assert pm1 is pm2

    def test_templates_dir_exists(self):
        """Test that templates directory exists."""
        pm = get_prompt_manager()
        assert pm.templates_dir.exists()

    def test_get_default_template(self):
        """Test getting default coder template."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment(model_name="unknown-model")
        prompt = pm.get_system_prompt(ctx, template_name="coder")

        assert len(prompt) > 0
        assert "AMCP" in prompt

    def test_get_anthropic_template(self):
        """Test getting Anthropic-specific template."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment(model_name="claude-sonnet-4")
        prompt = pm.get_system_prompt(ctx, template_name="coder")

        # Should use anthropic template
        assert "AMCP" in prompt

    def test_explorer_template(self):
        """Test explorer subagent template."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment()
        prompt = pm.get_system_prompt(ctx, template_name="explorer")

        assert "Explorer" in prompt or "explore" in prompt.lower()

    def test_planner_template(self):
        """Test planner subagent template."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment()
        prompt = pm.get_system_prompt(ctx, template_name="planner")

        assert "Planner" in prompt or "plan" in prompt.lower()

    def test_initialize_template(self):
        """Test initialize template for AGENTS.md generation."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment()
        prompt = pm.get_system_prompt(ctx, template_name="initialize")

        assert "AGENTS.md" in prompt

    def test_tools_list_in_prompt(self):
        """Test that tools list is rendered in prompt."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment(
            available_tools=["read_file", "grep", "bash"]
        )
        prompt = pm.get_system_prompt(ctx, template_name="coder")

        assert "read_file" in prompt
        assert "grep" in prompt
        assert "bash" in prompt

    def test_environment_variables_in_prompt(self):
        """Test that environment variables are rendered."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment(working_dir="/test/dir")
        prompt = pm.get_system_prompt(ctx, template_name="coder")

        assert "/test/dir" in prompt

    def test_conditional_git_section(self):
        """Test that git section is conditional."""
        pm = get_prompt_manager()

        # Non-git directory
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = PromptContext.from_environment(working_dir=tmpdir)
            prompt = pm.get_system_prompt(ctx, template_name="coder")
            # Should not have git branch info
            assert "Git branch:" not in prompt or "{{if is_git_repo}}" in prompt

    def test_skills_section_conditional(self):
        """Test that skills section is conditional."""
        pm = get_prompt_manager()

        # Without skills
        ctx = PromptContext.from_environment(skills_xml="")
        prompt = pm.get_system_prompt(ctx, template_name="coder")
        assert "<skills_usage>" not in prompt

        # With skills
        ctx = PromptContext.from_environment(
            skills_xml="<skills><skill>test</skill></skills>"
        )
        prompt = pm.get_system_prompt(ctx, template_name="coder")
        assert "skills" in prompt.lower()


class TestPromptContent:
    """Tests for actual prompt content quality."""

    def test_critical_rules_present(self):
        """Test that critical rules are in the prompt."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment()
        prompt = pm.get_system_prompt(ctx, template_name="coder")

        # Key rules should be present
        assert "READ BEFORE EDITING" in prompt or "read" in prompt.lower()
        assert "AUTONOMOUS" in prompt or "autonomous" in prompt.lower()

    def test_workflow_section_present(self):
        """Test that workflow section is in the prompt."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment()
        prompt = pm.get_system_prompt(ctx, template_name="coder")

        assert "workflow" in prompt.lower()

    def test_editing_guidelines_present(self):
        """Test that editing guidelines are in the prompt."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment()
        prompt = pm.get_system_prompt(ctx, template_name="coder")

        assert "edit" in prompt.lower()
        assert "whitespace" in prompt.lower() or "exact" in prompt.lower()

    def test_communication_style_present(self):
        """Test that communication style is in the prompt."""
        pm = get_prompt_manager()
        ctx = PromptContext.from_environment()
        prompt = pm.get_system_prompt(ctx, template_name="coder")

        assert "concise" in prompt.lower() or "minimal" in prompt.lower()


class TestCustomTemplates:
    """Tests for custom template loading."""

    def test_custom_templates_dir(self):
        """Test loading from custom templates directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a custom template
            template_path = Path(tmpdir) / "custom.md"
            template_path.write_text("Custom template for ${working_dir}")

            pm = PromptManager(templates_dir=Path(tmpdir))
            ctx = PromptContext.from_environment(working_dir="/my/dir")
            prompt = pm.get_system_prompt(ctx, template_name="custom")

            assert "Custom template" in prompt
            assert "/my/dir" in prompt

    def test_fallback_to_default(self):
        """Test fallback to default when template not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = PromptManager(templates_dir=Path(tmpdir))
            ctx = PromptContext.from_environment()
            prompt = pm.get_system_prompt(ctx, template_name="nonexistent")

            # Should use built-in default
            assert "AMCP" in prompt
