"""Tests for the project rules loading module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from amcp.project_rules import (
    AGENTS_FILE_NAMES,
    ProjectRulesLoader,
    discover_project_agents_files,
    find_agents_file,
    find_git_root,
    format_rules_section,
    get_global_agents_file,
    get_project_rules_info,
    load_project_rules,
    parse_external_references,
)


class TestFindGitRoot:
    """Tests for find_git_root function."""

    def test_finds_git_root(self):
        """Test finding git root in a git repository."""
        # Current project should be in a git repo
        cwd = Path.cwd()
        root = find_git_root(cwd)
        # May or may not be in a git repo depending on test environment
        if root:
            assert (root / ".git").exists()

    def test_returns_none_outside_git(self):
        """Test returns None when not in a git repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_git_root(Path(tmpdir))
            assert result is None


class TestFindAgentsFile:
    """Tests for find_agents_file function."""

    def test_finds_agents_md(self):
        """Test finding AGENTS.md file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            agents_file = tmppath / "AGENTS.md"
            agents_file.write_text("# Project Rules")

            result = find_agents_file(tmppath)
            assert result == agents_file

    def test_priority_order(self):
        """Test that AGENTS.md has priority over other names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create multiple files
            (tmppath / "agents.md").write_text("lowercase")
            (tmppath / "AGENTS.md").write_text("uppercase")

            result = find_agents_file(tmppath)
            assert result.name == "AGENTS.md"

    def test_returns_none_when_not_found(self):
        """Test returns None when no agents file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_agents_file(Path(tmpdir))
            assert result is None


class TestDiscoverProjectAgentsFiles:
    """Tests for discover_project_agents_files function."""

    def test_discovers_single_file(self):
        """Test discovering a single AGENTS.md file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            agents_file = tmppath / "AGENTS.md"
            agents_file.write_text("# Rules")

            files = discover_project_agents_files(tmppath)
            assert len(files) == 1
            assert files[0] == agents_file

    def test_discovers_nested_files(self):
        """Test discovering files from nested directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create a fake git root so boundary is set correctly
            (tmppath / ".git").mkdir()

            # Create nested structure
            subdir = tmppath / "src" / "app"
            subdir.mkdir(parents=True)

            root_file = tmppath / "AGENTS.md"
            root_file.write_text("# Root rules")

            sub_file = subdir / "AGENTS.md"
            sub_file.write_text("# App rules")

            # Discover from subdir
            files = discover_project_agents_files(subdir)

            # Should find both, with root first
            assert len(files) == 2
            assert files[0] == root_file
            assert files[1] == sub_file


class TestParseExternalReferences:
    """Tests for parse_external_references function."""

    def test_parses_references(self):
        """Test parsing @references from content."""
        content = """
# Project Rules

See @rules/general.md for general guidelines.
Also check @docs/coding-standards.md for coding standards.
"""
        refs = parse_external_references(content)
        assert "rules/general.md" in refs
        assert "docs/coding-standards.md" in refs

    def test_no_references(self):
        """Test with content without references."""
        content = "# Simple rules\nNo external references here."
        refs = parse_external_references(content)
        assert refs == []


class TestFormatRulesSection:
    """Tests for format_rules_section function."""

    def test_formats_with_header(self):
        """Test formatting adds header and footer."""
        filepath = Path("/project/AGENTS.md")
        content = "# My Rules\n\nDo this."

        result = format_rules_section(filepath, content)

        assert "Project Rules:" in result
        assert "# My Rules" in result
        assert "Do this." in result


class TestProjectRulesLoader:
    """Tests for ProjectRulesLoader class."""

    def test_empty_when_no_files(self):
        """Test returns empty when no agents files found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = ProjectRulesLoader(Path(tmpdir))
            rules = loader.load_rules()
            assert rules == ""

    def test_loads_single_file(self):
        """Test loading a single AGENTS.md file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            agents_file = tmppath / "AGENTS.md"
            agents_file.write_text("# Test Rules\n\nRule 1: Be awesome")

            loader = ProjectRulesLoader(tmppath)
            rules = loader.load_rules()

            assert "Test Rules" in rules
            assert "Rule 1: Be awesome" in rules

    def test_caches_results(self):
        """Test that results are cached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            agents_file = tmppath / "AGENTS.md"
            agents_file.write_text("# Rules")

            loader = ProjectRulesLoader(tmppath)
            rules1 = loader.load_rules()
            rules2 = loader.load_rules()

            assert rules1 == rules2
            assert loader._cached_rules is not None

    def test_reload_clears_cache(self):
        """Test reload clears cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            agents_file = tmppath / "AGENTS.md"
            agents_file.write_text("# Original")

            loader = ProjectRulesLoader(tmppath)
            loader.load_rules()

            # Modify file
            agents_file.write_text("# Updated")
            loader.reload()
            updated = loader.load_rules()

            assert "Updated" in updated

    def test_get_rules_summary(self):
        """Test getting rules summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            agents_file = tmppath / "AGENTS.md"
            agents_file.write_text("# Rules\n@extra/rules.md")

            loader = ProjectRulesLoader(tmppath)
            loader.load_rules()

            summary = loader.get_rules_summary()

            assert summary["has_rules"] is True
            assert summary["file_count"] == 1
            assert "extra/rules.md" in summary["external_references"]


class TestLoadProjectRules:
    """Tests for load_project_rules convenience function."""

    def test_loads_rules(self):
        """Test convenience function loads rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "AGENTS.md").write_text("# Quick Rules")

            rules = load_project_rules(tmppath)
            assert "Quick Rules" in rules


class TestGetProjectRulesInfo:
    """Tests for get_project_rules_info function."""

    def test_returns_info(self):
        """Test getting project rules info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "AGENTS.md").write_text("# Info Test")

            info = get_project_rules_info(tmppath)

            assert "work_dir" in info
            assert "discovered_files" in info
            assert len(info["discovered_files"]) == 1


class TestGlobalAgentsFile:
    """Tests for global agents file handling."""

    def test_get_global_file_not_exists(self):
        """Test when global file doesn't exist."""
        with patch("amcp.project_rules.GLOBAL_CONFIG_DIR", Path("/nonexistent")):
            result = get_global_agents_file()
            assert result is None

    def test_global_file_included_in_discovery(self):
        """Test global file is included when discovering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create global config dir with AGENTS.md
            global_dir = tmppath / "global"
            global_dir.mkdir()
            global_file = global_dir / "AGENTS.md"
            global_file.write_text("# Global Rules")

            # Create project dir
            project_dir = tmppath / "project"
            project_dir.mkdir()
            project_file = project_dir / "AGENTS.md"
            project_file.write_text("# Project Rules")

            with patch("amcp.project_rules.GLOBAL_CONFIG_DIR", global_dir):
                loader = ProjectRulesLoader(project_dir)
                files = loader.discover_files()

                # Should include both global and project files
                assert len(files) == 2
                assert global_file in files
                assert project_file in files
