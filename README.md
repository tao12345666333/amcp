# AMCP

[![PyPI version](https://badge.fury.io/py/amcp-agent.svg)](https://badge.fury.io/py/amcp-agent)
[![CI](https://github.com/tao12345666333/amcp/workflows/CI/badge.svg)](https://github.com/tao12345666333/amcp/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

tags:
- building-mcp-track-creative
- mcp-in-action-track-consumer
- mcp-in-action-track-creative
---

# AMCP

A Lego-style coding agent CLI with built-in tools (grep, read files, bash execution) and MCP server integration for extended capabilities (web search, etc.).

X: https://x.com/zhangjintao9020/status/1995170132973466018?s=20
Demo: https://drive.google.com/file/d/1FGoY4I_JFQ1FSz19XlVJZ6Z4lWUucD7a/view?usp=sharing


## Features

- **Built-in Tools**: read_file, grep, bash, think, todo, write_file, edit_file
- **MCP Integration**: Connect to any MCP server for extended capabilities
- **Conversation History**: Persistent sessions across runs
- **Flexible Configuration**: YAML-based agent specifications
- **Tool Calling**: Automatic tool selection and execution
- **ACP Support**: Full Agent Client Protocol support for IDE integration (Zed, etc.)
- **AGENTS.md Support**: Auto-load project-specific rules from `AGENTS.md` files
- **Smart Context Compaction**: Intelligent context management with dynamic thresholds
- **Multi-Agent System**: Primary/Subagent architecture with built-in agent types (coder, explorer, planner)
- **Event Bus**: Publish/subscribe system for agent communication and extensibility
- **Hooks System**: Extensible hooks for tool validation, logging, and custom behaviors

## Installation

### Quick Run with uvx (no install needed)

```bash
# Run directly without installation (like npx)
uvx amcp-agent
```

### From PyPI

```bash
# Install from PyPI
pip install amcp-agent

# Or with uv
uv pip install amcp-agent

# With Anthropic Claude support
pip install amcp-agent[anthropic]
```

### From Source (development)

```bash
# Clone the repository
git clone https://github.com/tao12345666333/amcp.git
cd amcp

# using uv (recommended)
uv venv && source .venv/bin/activate
uv pip install -e .

# or with pip
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Usage

```bash
# Initialize config
amcp init

# Agent with tool calling (default command)
amcp  # interactive mode with conversation history
amcp --once "create a hello.py file with a hello function"  # single message
amcp --list  # list available agent specifications
amcp --agent path/to/agent.yaml  # use custom agent spec
amcp --session my-session  # use specific session ID
amcp --clear  # clear conversation history

# MCP server management
amcp mcp tools --server exa
amcp mcp call --server exa --tool web_search_exa --args '{"query":"rust async"}'

# Run as ACP agent (for IDE integration)
amcp-acp
```

## ACP (Agent Client Protocol) Support

AMCP fully supports the [Agent Client Protocol](https://agentclientprotocol.com/) for integration with IDEs like Zed.

### Features

- **Session Management**: Create, load, and list sessions
- **Session Modes**: Switch between `ask`, `architect`, and `code` modes
  - `ask`: Request permission before making changes
  - `architect`: Design and plan without implementation
  - `code`: Full tool access for implementation
- **Slash Commands**: `/clear`, `/plan`, `/search`, `/help`
- **Agent Plans**: Visual execution plans for complex tasks
- **Permission Requests**: User approval for sensitive operations
- **Client Capabilities**: Use client's filesystem and terminal when available

### Running as ACP Agent

```bash
# Start the ACP agent server (stdio transport)
amcp-acp
```

### Zed Integration

Add to your Zed settings (`~/.config/zed/settings.json`):

```json
{
  "agent": {
    "profiles": {
      "amcp": {
        "name": "AMCP",
        "provider": {
          "type": "acp",
          "command": "amcp-acp"
        }
      }
    },
    "default_profile": "amcp"
  }
}
```

## Built-in Tools

- **read_file**: Read text files from the workspace
- **grep**: Search for patterns in files using ripgrep
- **bash**: Execute bash commands for file operations and system tasks
- **think**: Internal reasoning and planning
- **todo**: Manage a todo list to track tasks during complex operations
- **write_file**: Write content to files (can be disabled via config)
- **edit_file**: Edit files with search and replace (can be disabled via config)
- **task**: Spawn sub-agents for parallel task execution

## Config

The CLI loads MCP servers from `~/.config/amcp/config.toml`.
Generate a starter config:

```bash
amcp init
```

Example (OpenAI-compatible API):

```toml
[servers.exa]
url = "https://mcp.exa.ai/mcp"

[servers.custom]
command = "npx"
args = ["-y", "@some/mcp-server"]
env.API_KEY = "your-key"

[chat]
api_type = "openai"  # "openai" (default) or "anthropic"
base_url = "https://api.openai.com/v1"
model = "gpt-4o"
api_key = "your-api-key"
mcp_tools_enabled = true
write_tool_enabled = true  # Enable/disable built-in write_file tool
edit_tool_enabled = true   # Enable/disable built-in edit_file tool
```

Example (OpenAI Responses API):

```toml
[chat]
api_type = "openai_responses"
model = "gpt-4o"
api_key = "your-api-key"
```

Example (Anthropic Claude):

```toml
[chat]
api_type = "anthropic"
model = "claude-sonnet-4-20250514"
api_key = "your-anthropic-api-key"  # or set ANTHROPIC_API_KEY env var
```

To use Anthropic, install with: `pip install amcp-agent[anthropic]`

## Hooks System

AMCP provides a flexible hooks system to extend and customize agent behavior. Hooks can:
- Validate and modify tool inputs before execution
- Process tool outputs after execution
- Block dangerous operations
- Log and audit agent activities

### Quick Example

Create `.amcp/hooks.toml` in your project:

```toml
[hooks.PreToolUse]
[[hooks.PreToolUse.handlers]]
matcher = "write_file|edit_file"
type = "python"
script = "./scripts/validate-writes.py"
timeout = 30

[[hooks.PostToolUse.handlers]]
matcher = "*"
type = "command"
command = "echo 'Tool executed' >> /tmp/tool_log.txt"
```

See [docs/hooks.md](docs/hooks.md) for full documentation.

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone <repo-url>
cd AMCP

# Install with development dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test
pytest tests/test_tools.py -v
```

### Code Quality

```bash
# Lint code
make lint

# Format code
make format

# Type check
make type-check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed development guidelines.

## Notes
- `rg` (ripgrep) must be installed and on PATH for the grep tool.
- MCP servers must be installed separately and runnable (stdio transport).

## License

Apache-2.0
