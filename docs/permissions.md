# AMCP Permissions System

AMCP's permission system allows users to precisely control which tools and commands can be executed, which require approval, and which should be denied. The system is designed to be simple yet flexible, while providing more powerful features than similar tools.

## Design Philosophy

AMCP's permission system is based on the following core principles:

1. **Secure by Default**: Dangerous operations require user confirmation by default
2. **Flexible Configuration**: Supports fine-grained control at global, tool, and command levels
3. **Pattern Matching**: Uses wildcards for flexible rule matching
4. **Session Memory**: Supports "Always Allow" to avoid repeated confirmations
5. **Delegatable**: Supports delegating decisions to external programs

## Quick Start

### Basic Configuration

Add permission configuration to `~/.config/amcp/config.toml`:

```toml
[permissions]
# Global default rules
"*" = "allow"  # allow, ask, deny

# Tool-level rules
bash = "ask"           # All bash commands require confirmation
read_file = "allow"    # Allow file reading
write_file = "ask"     # File writing requires confirmation
apply_patch = "ask"    # Applying patches requires confirmation

# MCP tool rules
"mcp.*" = "ask"        # All MCP tools require confirmation
```

### Fine-grained Control

```toml
[permissions.bash]
# Bash command-level rules
"*" = "ask"                    # Default requires confirmation
"git status" = "allow"         # Allow git status
"git log *" = "allow"          # Allow git log with arguments
"git diff *" = "allow"         # Allow git diff
"git commit *" = "ask"         # git commit requires confirmation
"git push *" = "ask"           # git push requires confirmation
"rm *" = "deny"                # Deny rm command
"rm -rf *" = "deny"            # Deny rm -rf
"sudo *" = "deny"              # Deny sudo
"curl *" = "ask"               # curl requires confirmation
"wget *" = "ask"               # wget requires confirmation

[permissions.read_file]
"*" = "allow"                  # Default allow reading
"*.env" = "deny"               # Deny reading .env files
"*.env.*" = "deny"             # Deny reading .env.* files
".env.example" = "allow"       # Allow reading example config
"**/secrets/*" = "deny"        # Deny reading secrets directory
"**/.ssh/*" = "deny"           # Deny reading SSH directory

[permissions.write_file]
"*" = "ask"                    # Default requires confirmation
"*.md" = "allow"               # Allow writing Markdown files
"*.txt" = "allow"              # Allow writing text files
"**/node_modules/*" = "deny"   # Deny writing to node_modules
"**/.git/*" = "deny"           # Deny writing to .git directory

[permissions.apply_patch]
"*" = "ask"                    # Patch operations default to confirmation
"*.test.*" = "allow"           # Test files can be modified directly
"*_test.go" = "allow"          # Go test files can be modified directly
```

## Permission Actions

Each rule can be set to one of the following actions:

| Action | Description |
|--------|-------------|
| `allow` | Allow execution without user confirmation |
| `ask` | Require user confirmation before execution |
| `deny` | Deny execution, block the operation |
| `delegate` | Delegate the decision to an external program |

## Pattern Matching

AMCP uses wildcards for pattern matching:

| Pattern | Description | Example |
|---------|-------------|---------|
| `*` | Match zero or more characters (not crossing paths) | `*.py` matches `test.py` |
| `**` | Match any level of path | `**/*.py` matches `a/b/c.py` |
| `?` | Match a single character | `file?.txt` matches `file1.txt` |
| `[abc]` | Match any character in the set | `[abc].txt` matches `a.txt` |

### Rule Priority

Rules are matched from top to bottom, and **the last matching rule takes effect**. This allows you to set default rules and then add exceptions:

```toml
[permissions.bash]
"*" = "ask"              # 1. Default requires confirmation
"git *" = "allow"        # 2. git commands are allowed
"git push *" = "ask"     # 3. But git push still requires confirmation
```

For the command `git push origin main`:
1. Matches `*` → ask
2. Matches `git *` → allow
3. Matches `git push *` → ask (final result)

## Built-in Permission Types

AMCP supports the following permission types:

### Tool Permissions

| Permission Name | Description | Match Content |
|-----------------|-------------|---------------|
| `read_file` | Read file | File path |
| `write_file` | Write file | File path |
| `apply_patch` | Apply patch | Target file path |
| `bash` | Execute shell command | Full command line |
| `grep` | Search file content | Search pattern |
| `task` | Create subtask | Task type |

### MCP Tool Permissions

| Permission Name | Description | Match Content |
|-----------------|-------------|---------------|
| `mcp.*` | All MCP tools | Tool name |
| `mcp.exa.*` | MCP tools from specific server | Tool name |
| `mcp.exa.search` | Specific MCP tool | Tool arguments |

### Security Guard Permissions

| Permission Name | Default Action | Description |
|-----------------|----------------|-------------|
| `external_path` | `ask` | Triggered when accessing paths outside the working directory |
| `doom_loop` | `ask` | Triggered when detecting repeated calls to the same tool |
| `network_write` | `ask` | Triggered when executing operations that may cause network writes |
| `destructive_action` | `ask` | Triggered when executing destructive operations (e.g., rm -rf) |

## Decision Delegation

For complex scenarios, you can delegate permission decisions to an external program:

```toml
[permissions]
bash = { action = "delegate", to = "amcp-permission-helper" }
```

The external program receives a JSON-formatted request via standard input:

```json
{
  "tool": "bash",
  "arguments": {"command": "git push origin main"},
  "session_id": "abc123",
  "working_directory": "/path/to/project"
}
```

The program returns its decision via exit code:
- `0` - Allow
- `1` - Ask user
- `2` - Deny (stderr will be passed to the model)

Example Python script:

```python
#!/usr/bin/env python3
import json
import os
import sys

# Get tool name from environment variable
tool_name = os.environ.get("AMCP_TOOL_NAME", "")

# Read arguments from standard input
arguments = json.loads(sys.stdin.read())

# Allow all non-bash tools
if tool_name != "bash":
    sys.exit(0)

# Deny git push
cmd = arguments.get("command", "")
if "git push" in cmd:
    print("Please verify changes locally before pushing", file=sys.stderr)
    sys.exit(2)

# Other commands need to ask the user
sys.exit(1)
```

## User Interaction

When a rule is set to `ask`, AMCP requests user confirmation. Users can choose:

| Option | Description |
|--------|-------------|
| **Allow Once** | Allow this execution only |
| **Always Allow** | Remember this type of operation, don't ask again in this session |
| **Reject** | Deny this execution |

### Batch Authorization

When selecting "Always Allow", AMCP intelligently generates authorization patterns. For example:

- Execute `git status`, select Always → Authorize `git status*`
- Execute `npm install lodash`, select Always → Authorize `npm install *`

## Permission Modes

AMCP supports three session-level permission modes for quickly switching overall permission policies:

| Mode | Description | Use Case |
|------|-------------|----------|
| `normal` | Follow configured rules (default) | Daily development |
| `yolo` | Auto-allow all operations | Trusted tasks, demos |
| `strict` | All operations require confirmation | Security-sensitive environments |

### Switching with `/mode` Command

Use the `/mode` command in a session to switch permission modes:

```
/mode              # View current mode and available options
/mode normal       # Switch to normal mode
/mode yolo         # Switch to YOLO mode
/mode strict       # Switch to strict mode
```

### Starting with `--yolo` Flag

Add the `--yolo` flag when starting AMCP to enter YOLO mode directly:

```bash
# YOLO mode: auto-allow all operations
amcp --yolo

# Combined with other arguments
amcp --yolo --once "Create a hello world program"
```

> ⚠️ **Warning**: YOLO mode auto-allows all operations. Use only in fully trusted environments.

### STRICT Mode

In STRICT mode, even operations configured as `allow` require confirmation:

```
/mode strict
```

Note: STRICT mode still respects `deny` rules - denied operations won't become confirmable.

## Built-in Default Rules

If no permission rules are configured, AMCP uses the following defaults:

```toml
[permissions]
# Read-only operations are allowed by default
read_file = "allow"
grep = "allow"
think = "allow"
todo = "allow"

# Write operations require confirmation
bash = "ask"
write_file = "ask"
apply_patch = "ask"
task = "ask"

# MCP tools require confirmation
"mcp.*" = "ask"

# Security guards
external_path = "ask"
doom_loop = "ask"

[permissions.read_file]
"*" = "allow"
"*.env" = "deny"
"*.env.*" = "deny"
".env.example" = "allow"
```

## Command Line Tools

AMCP provides command line tools for managing permissions:

```bash
# Edit permission rules
amcp permissions edit

# Test permission rules
amcp permissions test bash --cmd "git push origin main"

# List current rules
amcp permissions list

# Reset to default rules
amcp permissions reset
```

### Testing Permissions

Use `amcp permissions test` to verify rule configuration:

```bash
$ amcp permissions test bash --cmd "git status"
tool: bash
arguments: {"command": "git status"}
action: allow
matched-rule: permissions.bash."git *"
source: user

$ amcp permissions test bash --cmd "rm -rf /"
tool: bash
arguments: {"command": "rm -rf /"}
action: deny
matched-rule: permissions.bash."rm *"
source: user
```

## Agent-Level Permissions

You can configure different permission rules for different Agents:

```toml
# Global permissions
[permissions]
bash = "ask"

# explorer Agent permissions (read-only)
[agents.explorer.permissions]
bash = "deny"
write_file = "deny"
apply_patch = "deny"

# coder Agent permissions (full permissions)
[agents.coder.permissions]
bash = "ask"
write_file = "ask"
apply_patch = "ask"
```

You can also specify permissions in the Agent definition file:

```markdown
---
name: readonly-explorer
description: Read-only code explorer
permissions:
  bash: deny
  write_file: deny
  apply_patch: deny
---

You are a read-only code explorer that can only view code, not modify it.
```

## Best Practices

### 1. Security First

```toml
[permissions]
# Always deny dangerous operations
"*" = "ask"

[permissions.bash]
"rm -rf *" = "deny"
"sudo *" = "deny"
"chmod 777 *" = "deny"
"> /dev/*" = "deny"
```

### 2. Development Efficiency

```toml
[permissions.bash]
"*" = "ask"
# Allow common safe commands to pass quickly
"git status" = "allow"
"git log *" = "allow"
"git diff *" = "allow"
"git branch *" = "allow"
"ls *" = "allow"
"cat *" = "allow"
"head *" = "allow"
"tail *" = "allow"
"grep *" = "allow"
"find *" = "allow"
# Build commands
"make *" = "allow"
"npm run *" = "allow"
"pnpm *" = "allow"
"cargo *" = "allow"
"go build *" = "allow"
"go test *" = "allow"
```

### 3. Protect Sensitive Information

```toml
[permissions.read_file]
"*" = "allow"
# Protect sensitive configs
"*.env" = "deny"
"*.env.*" = "deny"
".env.example" = "allow"
"**/secrets/*" = "deny"
"**/*.pem" = "deny"
"**/*.key" = "deny"
"**/.ssh/*" = "deny"
"**/credentials*" = "deny"
```

### 4. CI/CD Environments

```toml
# Non-interactive mode: don't allow any operations requiring confirmation
[permissions]
"*" = "allow"

[permissions.bash]
"*" = "allow"
# But still deny dangerous operations
"rm -rf /" = "deny"
"rm -rf /*" = "deny"
```

## Comparison with Other Tools

| Feature | AMCP | Amp | OpenCode | Codex |
|---------|------|-----|----------|-------|
| Global rules | ✅ | ✅ | ✅ | ✅ |
| Tool-level rules | ✅ | ✅ | ✅ | ✅ |
| Command-level rules | ✅ | ✅ | ✅ | ❌ |
| File path rules | ✅ | ❌ | ✅ | ❌ |
| Wildcard matching | ✅ | ✅ | ✅ | ❌ |
| Decision delegation | ✅ | ✅ | ❌ | ❌ |
| Agent-level permissions | ✅ | ❌ | ✅ | ❌ |
| Security guards | ✅ | ❌ | ✅ | ✅ |
| Rule testing | ✅ | ✅ | ❌ | ❌ |
| TOML configuration | ✅ | ❌ | ✅ | ❌ |
| Rule inheritance | ✅ | ❌ | ❌ | ❌ |

## Technical Appendix

### Configuration File Locations

- Global config: `~/.config/amcp/config.toml`
- Project config: `.amcp/permissions.toml` (higher priority)

### Environment Variables

| Variable | Description |
|----------|-------------|
| `AMCP_PERMISSIONS_MODE` | Options: `interactive` (default), `strict`, `permissive` |
| `AMCP_TOOL_NAME` | Available to delegate programs: name of the current tool being executed |

### Rule Merge Order

1. Built-in default rules (lowest priority)
2. Global config `~/.config/amcp/config.toml`
3. Project config `.amcp/permissions.toml`
4. Agent-level config
5. Session-level "Always Allow" (highest priority)
