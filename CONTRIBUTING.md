# Contributing to AMCP

## Development Setup

```bash
# Clone the repository
git clone <repo-url>
cd amcp

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Or using uv
uv pip install -e ".[dev]"
```

## Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test
pytest tests/test_config.py
```

## Code Quality

```bash
# Lint code
make lint

# Format code
make format

# Type check
make type-check
```

## Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

## Project Structure

```
amcp/
├── src/amcp/          # Main package
│   ├── __init__.py
│   ├── cli.py         # CLI entry point
│   ├── agent.py       # Agent logic
│   ├── tools.py       # Built-in tools
│   ├── config.py      # Configuration
│   └── mcp_client.py  # MCP integration
├── tests/             # Test suite
├── .github/workflows/ # CI/CD
└── pyproject.toml     # Project metadata
```
