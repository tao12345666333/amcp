# AMCP Project Rules

## Project Overview

AMCP (Agent Model Context Protocol) is a Python-based AI coding agent with multi-agent support, MCP integration, and smart context management.

## Code Style

- Python 3.11+ with modern type hints
- Follow PEP 8 conventions
- Maximum line length: 100 characters (enforced by ruff)
- Use dataclasses for configuration and data structures

## Architecture Patterns

- Modular design with clear separation of concerns
- Tools are implemented as classes inheriting from `BaseTool`
- Agents are configured via `AgentSpec` and `ResolvedAgentSpec`
- Configuration uses TOML format stored in `~/.config/amcp/`

## Testing

- Use pytest for all tests
- Test files should match source files: `test_<modulename>.py`
- Prefer unit tests with mocking for external dependencies
- Maintain reasonable test coverage

## File Structure

```
src/amcp/
├── agent.py         # Main Agent class
├── agent_spec.py    # Agent configuration specs
├── tools.py         # Tool definitions and registry
├── cli.py           # Typer CLI commands
├── config.py        # TOML configuration handling
├── compaction.py    # Smart context compaction
├── models_db.py     # Model database from models.dev
├── project_rules.py # AGENTS.md loading
└── ...
```

## Dependencies

- `typer` for CLI
- `httpx` for HTTP requests
- `rich` for terminal UI
- `pydantic` for data validation

## Coding Guidelines

1. **Error Handling**: Use meaningful exception classes
2. **Logging**: Use the `logging` module, not print statements
3. **Configuration**: Support both config files and environment variables
4. **Documentation**: Docstrings for all public functions and classes

## Pre-Commit Checks

Before committing code, always run the following checks and ensure they pass:

```bash
# Format code
make format

# Check for lint errors
ruff check src/

# If lint errors are found, fix them with:
ruff check src/ --fix
```

## Release Workflow

When releasing a new version, follow these steps **in order**:

### 1. Update Version Numbers

Version numbers must be updated in **ALL** of the following locations:

| File | Location | Format |
|------|----------|--------|
| `pyproject.toml` | Line 3 | `version = "X.Y.Z"` |
| `src/amcp/_version.py` | Line 7 | `__version__ = "X.Y.Z"` |
| `src/amcp/acp_agent.py` | In `initialize()` method | `version="X.Y.Z"` |

**Quick search command to verify all locations are updated:**
```bash
grep -rn "X.Y.Z" pyproject.toml src/amcp/_version.py src/amcp/acp_agent.py
```

### 2. Run Quality Checks

```bash
# Format code
ruff format src tests

# Check for lint errors and fix
ruff check src tests --fix

# Run all tests
python -m pytest tests/ -q
```

### 3. Commit and Tag

```bash
# Add all changes
git add -A

# Commit with version bump message
git commit -m "chore: bump version to X.Y.Z

Changes in this release:
- <list key changes>"

# Create annotated tag
git tag -a vX.Y.Z -m "Release vX.Y.Z"

# Push to remote with tags
git push origin main --tags
```

### 4. Verify Release

After pushing, verify the version is correct:
```bash
uvx amcp-agent -v
# Should show: amcp version X.Y.Z (git: <hash>)
```

### Version Numbering Guidelines

- **Patch (X.Y.Z → X.Y.Z+1)**: Bug fixes, documentation updates
- **Minor (X.Y.Z → X.Y+1.0)**: New features, non-breaking changes
- **Major (X.Y.Z → X+1.0.0)**: Breaking changes

