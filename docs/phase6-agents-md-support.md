# AGENTS.md Project Rules Support

AMCP now supports automatic loading of project-specific rules from `AGENTS.md` files. This feature allows you to define project guidelines, coding conventions, and AI-specific instructions that are automatically included in the agent's context.

## Overview

When AMCP starts, it automatically discovers and loads `AGENTS.md` files from:

1. **Global rules**: `~/.config/amcp/AGENTS.md`
2. **Project rules**: From the repository root to the current working directory

Rules are combined with global rules first (lowest priority) and project-specific rules last (highest priority).

## File Names

AMCP recognizes the following file names (in priority order):

- `AGENTS.md` (recommended)
- `AGENT.md`
- `.agents.md`
- `agents.md`

You can also create override files for temporary changes:

- `AGENTS.override.md`
- `AGENT.override.md`

## File Discovery

AMCP searches for `AGENTS.md` files by:

1. Finding the git repository root (if in a git repo)
2. Traversing from the root to the current working directory
3. Loading files in order from root to current directory

```
my-project/
├── .git/
├── AGENTS.md            # Loaded first (general project rules)
└── src/
    └── backend/
        └── AGENTS.md    # Loaded second (specific backend rules)
```

## Example AGENTS.md

```markdown
# Project Rules

## Code Style
- Use Python 3.11+ type hints
- Follow PEP 8 conventions
- Maximum line length: 100 characters

## Architecture
- Follow hexagonal architecture principles
- Keep business logic in domain layer
- Use dependency injection

## Testing
- Write unit tests for all new functions
- Target 80% code coverage
- Use pytest for testing

## Dependencies
- Prefer standard library over external packages
- Document why external dependencies are needed

## External Reference Files

For detailed coding standards, see:
@rules/python-style.md
@rules/testing-conventions.md
```

## External References

You can reference external rule files using the `@path/to/file.md` syntax. The agent will load these files on-demand when they're relevant to the current task.

This approach avoids context crowding by only loading relevant rules.

## Global Rules

Create a global `AGENTS.md` file for personal preferences that apply to all projects:

```bash
mkdir -p ~/.config/amcp
cat > ~/.config/amcp/AGENTS.md << 'EOF'
# Personal Preferences

## Coding Style
- Prefer explicit over implicit
- Add comments for non-obvious logic
- Use meaningful variable names

## Response Style
- Be concise in explanations
- Show code examples when helpful
- Explain trade-offs for design decisions
EOF
```

## CLI Integration

When AMCP loads project rules, it displays which files were loaded:

```
📋 Loaded project rules: AGENTS.md
```

## Programmatic Usage

```python
from amcp import load_project_rules, get_project_rules_info, ProjectRulesLoader
from pathlib import Path

# Quick load
rules = load_project_rules(Path.cwd())
print(rules)

# Get info without loading full content
info = get_project_rules_info(Path.cwd())
print(f"Found {info['file_count']} rule files")

# Advanced usage with loader
loader = ProjectRulesLoader(Path.cwd())
rules = loader.load_rules()
summary = loader.get_rules_summary()

print(f"Loaded {summary['file_count']} files")
print(f"External references: {summary['external_references']}")
```

## Agent Integration

The `Agent` class automatically loads project rules when processing messages:

```python
from amcp import Agent

agent = Agent()

# Rules are automatically loaded based on work_dir
await agent.run("Help me refactor this code", work_dir=Path.cwd())

# Check loaded rules
info = agent.get_project_rules_info()
print(f"Rules active: {info['has_rules']}")
```

## Best Practices

1. **Be Specific**: Write clear, actionable rules that the AI can follow
2. **Keep It Focused**: Don't overload with too many rules
3. **Use Hierarchy**: Put general rules in project root, specific rules in subdirectories
4. **Reference External Files**: Use `@path/to/file.md` for detailed guidelines
5. **Review Regularly**: Update rules as project conventions evolve

## Example Rules by Project Type

### Python Project

```markdown
# Python Project Rules

## Framework
- Flask for web API
- SQLAlchemy for database
- pytest for testing

## Standards
- Use dataclasses for DTOs
- Type hints on all public functions
- Docstrings in Google style
```

### TypeScript Project

```markdown
# TypeScript Project Rules

## Framework
- React for UI
- Express for API
- Jest for testing

## Standards
- Strict TypeScript mode
- Functional components with hooks
- ESLint + Prettier formatting
```

### Go Project

```markdown
# Go Project Rules

## Structure
- Follow standard layout
- Use interfaces for testability
- Keep packages focused

## Standards
- golangci-lint for linting
- Table-driven tests
- Error wrapping with context
```

## Troubleshooting

### Rules Not Loading

1. Check file name is supported (AGENTS.md, AGENT.md, etc.)
2. Ensure file is in git repository or work directory
3. Check file permissions

### Rules Conflicting

Later rules (closer to work directory) override earlier rules. Review the load order:

```python
info = get_project_rules_info(Path.cwd())
for f in info['discovered_files']:
    print(f)  # Shows load order
```
