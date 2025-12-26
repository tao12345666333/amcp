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
