Analyze this codebase and create/update **AGENTS.md** to help future agents work effectively in this repository.

<first_check>
Check if directory is empty or contains only config files. If so, stop and say:
"Directory appears empty or only contains config. Add source code first, then run this command to generate AGENTS.md."
</first_check>

<goal>
Document what an agent needs to know to work in this codebase - commands, patterns, conventions, gotchas.
</goal>

<discovery_process>
1. Check directory contents with `ls -la`
2. Look for existing rule files:
   - `.cursor/rules/*.md`
   - `.cursorrules`
   - `.github/copilot-instructions.md`
   - `claude.md`
   - `AGENTS.md`
   - `CLAUDE.md`
   - `.clinerules`
   Only read if they exist.
3. Identify project type from config files:
   - `pyproject.toml`, `setup.py` → Python
   - `package.json` → Node.js/JavaScript
   - `go.mod` → Go
   - `Cargo.toml` → Rust
   - `pom.xml`, `build.gradle` → Java
4. Find build/test/lint commands from:
   - Config files (pyproject.toml, package.json, etc.)
   - Makefile or Taskfile
   - CI configs (.github/workflows/, .gitlab-ci.yml)
   - README.md
5. Read representative source files to understand:
   - Code organization
   - Naming conventions
   - Testing patterns
   - Error handling style
6. If AGENTS.md exists, read and improve it
</discovery_process>

<content_to_include>
**Essential Commands** (whatever is relevant for this project):
- Build command
- Test command (unit, integration)
- Lint/format command
- Run/serve command
- Deploy command (if applicable)

**Code Organization**:
- Directory structure explanation
- Key modules and their purposes
- Entry points

**Conventions**:
- Naming conventions (files, functions, classes)
- Code style patterns
- Import organization
- Type annotations (if applicable)

**Testing**:
- Testing framework used
- Test file location pattern
- How to run specific tests
- Mocking patterns

**Important Gotchas**:
- Non-obvious patterns
- Common pitfalls
- Things that might trip up an agent

**Project-Specific Context**:
- Any relevant info from existing rule files
- Architecture decisions
- External dependencies or services
</content_to_include>

<format>
Use clear markdown sections. Structure based on what you find.
Aim for completeness - include everything an agent would need to know.
Use code blocks for commands.

Example structure:
```markdown
# Project Name

Brief description of what the project does.

## Quick Start

\`\`\`bash
# Install dependencies
command here

# Run tests
command here
\`\`\`

## Project Structure

- `src/` - Main source code
- `tests/` - Test files
...

## Development Commands

| Command | Description |
|---------|-------------|
| `make test` | Run all tests |
...

## Code Conventions

- Use snake_case for functions
- ...

## Testing

Test files are in `tests/` and follow the pattern `test_*.py`.
...

## Important Notes

- Note 1
- Note 2
```
</format>

<critical_rule>
Only document what you actually observe. Never invent commands, patterns, or conventions.
If you can't find something, don't include it.
</critical_rule>

<env>
Working directory: ${working_dir}
</env>
