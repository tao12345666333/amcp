"""Tests for the skills system."""

from __future__ import annotations

import pytest
from pathlib import Path
import tempfile
import shutil

from amcp.skills import (
    SkillManager,
    SkillMetadata,
    get_skill_manager,
    reset_skill_manager,
)


@pytest.fixture
def temp_skills_dir():
    """Create a temporary skills directory."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_skill_file(temp_skills_dir: Path):
    """Create a sample skill file."""
    skill_dir = temp_skills_dir / "test-skill"
    skill_dir.mkdir(parents=True)
    
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("""---
name: test-skill
description: A test skill for unit testing
---

# Test Skill

This is a test skill body.
""")
    
    return skill_file


@pytest.fixture
def skill_manager():
    """Create a fresh skill manager for each test."""
    reset_skill_manager()
    return SkillManager()


class TestSkillManager:
    """Tests for SkillManager class."""
    
    def test_skill_manager_creation(self, skill_manager: SkillManager):
        """Test creating a skill manager."""
        assert skill_manager is not None
        assert skill_manager.get_all_skills() == []
    
    def test_discover_skills_from_dir(self, skill_manager: SkillManager, temp_skills_dir: Path, sample_skill_file: Path):
        """Test discovering skills from a directory."""
        skills = skill_manager._discover_skills_from_dir(temp_skills_dir)
        
        assert len(skills) == 1
        skill = skills[0]
        assert skill.name == "test-skill"
        assert skill.description == "A test skill for unit testing"
        assert "Test Skill" in skill.body
    
    def test_parse_skill_file(self, skill_manager: SkillManager, sample_skill_file: Path):
        """Test parsing a skill file."""
        skill = skill_manager._parse_skill_file(sample_skill_file)
        
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A test skill for unit testing"
        assert "This is a test skill body" in skill.body
        assert skill.location == str(sample_skill_file)
    
    def test_parse_invalid_skill_file(self, skill_manager: SkillManager, temp_skills_dir: Path):
        """Test parsing an invalid skill file."""
        skill_dir = temp_skills_dir / "invalid-skill"
        skill_dir.mkdir()
        
        # No frontmatter
        invalid_file = skill_dir / "SKILL.md"
        invalid_file.write_text("No frontmatter here")
        
        skill = skill_manager._parse_skill_file(invalid_file)
        assert skill is None
    
    def test_skill_activation(self, skill_manager: SkillManager, temp_skills_dir: Path, sample_skill_file: Path):
        """Test skill activation and deactivation."""
        skill_manager._discover_skills_from_dir(temp_skills_dir)
        skills = skill_manager._discover_skills_from_dir(temp_skills_dir)
        skill_manager._add_skills_with_precedence(skills)
        
        # Initially not active
        assert not skill_manager.is_skill_active("test-skill")
        
        # Activate
        result = skill_manager.activate_skill("test-skill")
        assert result is True
        assert skill_manager.is_skill_active("test-skill")
        
        # Get active skills
        active = skill_manager.get_active_skills()
        assert len(active) == 1
        assert active[0].name == "test-skill"
        
        # Deactivate
        skill_manager.deactivate_skill("test-skill")
        assert not skill_manager.is_skill_active("test-skill")
    
    def test_skill_content(self, skill_manager: SkillManager, temp_skills_dir: Path, sample_skill_file: Path):
        """Test getting active skills content."""
        skills = skill_manager._discover_skills_from_dir(temp_skills_dir)
        skill_manager._add_skills_with_precedence(skills)
        
        # No active skills
        content = skill_manager.get_active_skills_content()
        assert content == ""
        
        # Activate skill
        skill_manager.activate_skill("test-skill")
        content = skill_manager.get_active_skills_content()
        
        assert "Active Skills" in content
        assert "test-skill" in content
        assert "This is a test skill body" in content
    
    def test_disabled_skills(self, skill_manager: SkillManager, temp_skills_dir: Path, sample_skill_file: Path):
        """Test disabling skills."""
        skills = skill_manager._discover_skills_from_dir(temp_skills_dir)
        skill_manager._add_skills_with_precedence(skills)
        
        # Disable the skill
        skill_manager.set_disabled_skills(["test-skill"])
        
        # Should not be able to activate disabled skill
        result = skill_manager.activate_skill("test-skill")
        assert result is False
        
        # Should not appear in get_skills
        enabled = skill_manager.get_skills()
        assert len(enabled) == 0
        
        # Should still appear in get_all_skills
        all_skills = skill_manager.get_all_skills()
        assert len(all_skills) == 1
        assert all_skills[0].disabled is True


class TestGlobalSkillManager:
    """Tests for global skill manager functions."""
    
    def test_get_skill_manager(self):
        """Test getting the global skill manager."""
        reset_skill_manager()
        sm = get_skill_manager()
        assert sm is not None
        
        # Same instance
        sm2 = get_skill_manager()
        assert sm is sm2
    
    def test_reset_skill_manager(self):
        """Test resetting the global skill manager."""
        sm1 = get_skill_manager()
        reset_skill_manager()
        sm2 = get_skill_manager()
        assert sm1 is not sm2
