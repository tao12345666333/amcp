---
name: python-expert
description: Python development best practices and advanced patterns
---

# Python Expert Skill

When working with Python code, apply these advanced patterns and best practices:

## Code Style
- Follow PEP 8 guidelines
- Use type hints for function signatures
- Prefer f-strings for string formatting
- Use meaningful variable and function names

## Modern Python Features
- Use dataclasses for data containers
- Prefer pathlib over os.path
- Use context managers for resource management
- Leverage generators for memory efficiency
- Use structural pattern matching (Python 3.10+)

## Error Handling
- Use specific exception types
- Provide meaningful error messages
- Log errors appropriately
- Consider using Result types for expected failures

## Testing
- Write unit tests with pytest
- Use fixtures for test setup
- Mock external dependencies
- Aim for high test coverage

## Project Structure
```
project/
├── src/
│   └── package/
│       ├── __init__.py
│       └── module.py
├── tests/
│   └── test_module.py
├── pyproject.toml
└── README.md
```

## Packaging
- Use pyproject.toml for configuration
- Define clear dependencies
- Use semantic versioning
