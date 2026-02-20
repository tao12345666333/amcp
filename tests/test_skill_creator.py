"""Tests for the built-in skill-creator and skills system enhancements."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from amcp.skills import SkillManager, SkillMetadata, reset_skill_manager

# --- Fixtures ---


@pytest.fixture(autouse=True)
def _reset_manager():
    """Reset global skill manager before each test."""
    reset_skill_manager()
    yield
    reset_skill_manager()


@pytest.fixture
def skill_manager():
    return SkillManager()


@pytest.fixture
def tmp_skill_dir(tmp_path: Path):
    """Create a temp directory with a sample skill."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: A test skill for unit testing\n---\n\n# My Skill\n\nTest skill body content."
    )
    return skill_dir


@pytest.fixture
def tmp_skills_root(tmp_path: Path, tmp_skill_dir: Path):
    """Return the skills root that contains a skill subdirectory."""
    return tmp_path


# --- Tests: Built-in Skills Discovery ---


class TestBuiltinSkillsDiscovery:
    def test_builtin_skills_dir_exists(self):
        """Built-in skills directory exists in the package."""
        sm = SkillManager()
        builtin_dir = sm.get_builtin_skills_dir()
        assert builtin_dir.is_dir(), f"Built-in skills dir not found: {builtin_dir}"

    def test_skill_creator_bundled(self):
        """skill-creator is bundled as a built-in skill."""
        sm = SkillManager()
        builtin_dir = sm.get_builtin_skills_dir()
        skill_creator_dir = builtin_dir / "skill-creator"
        assert skill_creator_dir.is_dir()
        assert (skill_creator_dir / "SKILL.md").is_file()

    def test_discover_finds_builtin_skills(self, tmp_path: Path):
        """discover_skills finds built-in skills even with empty user/project dirs."""
        sm = SkillManager()
        sm.discover_skills(project_root=tmp_path)

        names = [s.name for s in sm.get_skills()]
        assert "skill-creator" in names

    def test_builtin_skill_has_body(self, tmp_path: Path):
        """Built-in skill-creator has actual content in its body."""
        sm = SkillManager()
        sm.discover_skills(project_root=tmp_path)

        skill = sm.get_skill("skill-creator")
        assert skill is not None
        assert len(skill.body) > 100  # It should have substantial content
        assert "SKILL.md" in skill.body  # References the file format


class TestPrecedenceOrder:
    def test_user_overrides_builtin(self, tmp_path: Path):
        """User-level skills override built-in skills with the same name."""
        sm = SkillManager()

        # Create a user-level skill-creator that overrides the built-in
        user_skill_dir = tmp_path / "user-skills" / "skill-creator"
        user_skill_dir.mkdir(parents=True)
        (user_skill_dir / "SKILL.md").write_text(
            "---\nname: skill-creator\ndescription: User override\n---\n\nUser body."
        )

        # Discover with custom user dir
        builtin_skills = sm._discover_skills_from_dir(sm.get_builtin_skills_dir())
        user_skills = sm._discover_skills_from_dir(tmp_path / "user-skills")

        sm._add_skills_with_precedence(builtin_skills)
        sm._add_skills_with_precedence(user_skills)

        skill = sm.get_skill("skill-creator")
        assert skill is not None
        assert skill.description == "User override"
        assert skill.body == "User body."

    def test_project_overrides_all(self, tmp_path: Path):
        """Project-level skills override both built-in and user skills."""
        sm = SkillManager()

        # Create project-level skill
        project_skill_dir = tmp_path / ".amcp" / "skills" / "skill-creator"
        project_skill_dir.mkdir(parents=True)
        (project_skill_dir / "SKILL.md").write_text(
            "---\nname: skill-creator\ndescription: Project override\n---\n\nProject body."
        )

        sm.discover_skills(project_root=tmp_path)

        skill = sm.get_skill("skill-creator")
        assert skill is not None
        assert skill.description == "Project override"


# --- Tests: Skills Summary (Progressive Disclosure) ---


class TestSkillsSummary:
    def test_summary_empty_when_no_skills(self):
        """Summary is empty when no skills are discovered."""
        sm = SkillManager()
        assert sm.build_skills_summary() == ""

    def test_summary_contains_skill_names(self, tmp_path: Path):
        """Summary lists all skill names."""
        sm = SkillManager()
        sm.discover_skills(project_root=tmp_path)
        summary = sm.build_skills_summary()

        assert "skill-creator" in summary
        assert "<skills>" in summary
        assert "</skills>" in summary

    def test_summary_marks_active_skills(self, tmp_path: Path):
        """Active skills are marked with a star emoji."""
        sm = SkillManager()
        sm.discover_skills(project_root=tmp_path)
        sm.activate_skill("skill-creator")

        summary = sm.build_skills_summary()
        assert "⭐" in summary

    def test_summary_excludes_disabled_skills(self, tmp_path: Path):
        """Disabled skills are not in the summary."""
        sm = SkillManager()
        sm.discover_skills(project_root=tmp_path)
        sm.set_disabled_skills(["skill-creator"])

        summary = sm.build_skills_summary()
        assert "skill-creator" not in summary


class TestGetSkillContent:
    def test_get_existing_skill_content(self, tmp_path: Path):
        """get_skill_content returns body for existing skill."""
        sm = SkillManager()
        sm.discover_skills(project_root=tmp_path)

        content = sm.get_skill_content("skill-creator")
        assert content is not None
        assert len(content) > 0

    def test_get_nonexistent_skill_content(self, tmp_path: Path):
        """get_skill_content returns None for missing skill."""
        sm = SkillManager()
        sm.discover_skills(project_root=tmp_path)

        content = sm.get_skill_content("nonexistent-skill")
        assert content is None


# --- Tests: init_skill.py ---


class TestInitSkillScript:
    @pytest.fixture
    def init_script(self):
        return (
            Path(__file__).resolve().parent.parent
            / "src"
            / "amcp"
            / "builtin_skills"
            / "skill-creator"
            / "scripts"
            / "init_skill.py"
        )

    def test_creates_skill_directory(self, tmp_path: Path, init_script: Path):
        """init_skill.py creates a proper skill directory."""
        result = subprocess.run(
            [sys.executable, str(init_script), "test-skill", "--path", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

        skill_dir = tmp_path / "test-skill"
        assert skill_dir.is_dir()
        assert (skill_dir / "SKILL.md").is_file()

        content = (skill_dir / "SKILL.md").read_text()
        assert "name: test-skill" in content
        assert "description:" in content

    def test_creates_resource_directories(self, tmp_path: Path, init_script: Path):
        """init_skill.py creates requested resource directories."""
        result = subprocess.run(
            [sys.executable, str(init_script), "my-tool", "--path", str(tmp_path), "--resources", "scripts,references"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

        skill_dir = tmp_path / "my-tool"
        assert (skill_dir / "scripts").is_dir()
        assert (skill_dir / "references").is_dir()
        assert not (skill_dir / "assets").is_dir()

    def test_rejects_invalid_name(self, tmp_path: Path, init_script: Path):
        """init_skill.py rejects invalid skill names."""
        result = subprocess.run(
            [sys.executable, str(init_script), "INVALID_NAME!", "--path", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Invalid name" in result.stderr

    def test_rejects_existing_directory(self, tmp_path: Path, init_script: Path):
        """init_skill.py won't overwrite an existing skill directory."""
        (tmp_path / "existing").mkdir()
        result = subprocess.run(
            [sys.executable, str(init_script), "existing", "--path", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0


# --- Tests: validate_skill.py ---


class TestValidateSkillScript:
    @pytest.fixture
    def validate_script(self):
        return (
            Path(__file__).resolve().parent.parent
            / "src"
            / "amcp"
            / "builtin_skills"
            / "skill-creator"
            / "scripts"
            / "validate_skill.py"
        )

    def test_validates_good_skill(self, tmp_skill_dir: Path, validate_script: Path):
        """validate_skill.py passes for a valid skill."""
        result = subprocess.run(
            [sys.executable, str(validate_script), str(tmp_skill_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
        assert "✅" in result.stdout

    def test_fails_missing_skill_md(self, tmp_path: Path, validate_script: Path):
        """validate_skill.py fails when SKILL.md is missing."""
        empty_dir = tmp_path / "empty-skill"
        empty_dir.mkdir()
        result = subprocess.run(
            [sys.executable, str(validate_script), str(empty_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Missing SKILL.md" in result.stdout

    def test_fails_todo_description(self, tmp_path: Path, validate_script: Path):
        """validate_skill.py fails when description is a TODO."""
        skill_dir = tmp_path / "bad-desc"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: bad-desc\ndescription: TODO write description\n---\n\n# Body\n\nContent."
        )
        result = subprocess.run(
            [sys.executable, str(validate_script), str(skill_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "placeholder" in result.stdout.lower()

    def test_fails_name_mismatch(self, tmp_path: Path, validate_script: Path):
        """validate_skill.py fails when directory name doesn't match skill name."""
        skill_dir = tmp_path / "wrong-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: correct-name\ndescription: A skill with mismatched dir name\n---\n\n# Body\n\nContent."
        )
        result = subprocess.run(
            [sys.executable, str(validate_script), str(skill_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "does not match" in result.stdout

    def test_validates_builtin_skill_creator(self, validate_script: Path):
        """The bundled skill-creator itself passes validation."""
        builtin_skill_dir = Path(__file__).resolve().parent.parent / "src" / "amcp" / "builtin_skills" / "skill-creator"
        result = subprocess.run(
            [sys.executable, str(validate_script), str(builtin_skill_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Built-in skill-creator failed validation:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
