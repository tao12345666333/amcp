# amcp

A Lego-style coding agent CLI with built-in tools (grep, read files, bash execution) and MCP server integration for extended capabilities (web search, etc.).

## Install (editable)

```bash
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
```

## Built-in Tools

- **read_file**: Read text files from the workspace
- **grep**: Search for patterns in files using ripgrep
- **bash**: Execute bash commands for file operations and system tasks
- **think**: Internal reasoning and planning

## Config

The CLI loads MCP servers from `~/.config/amcp/config.toml`.
Generate a starter config:

```bash
amcp init
```

Example:

```toml
[servers.exa]
url = "https://mcp.exa.ai/mcp"

[servers.custom]
command = "npx"
args = ["-y", "@some/mcp-server"]
env.API_KEY = "your-key"

[chat]
base_url = "https://api.sambanova.ai/v1"
model = "DeepSeek-V3.1-Terminus"
api_key = "your-api-key"
mcp_tools_enabled = true
```

## Notes
- `rg` (ripgrep) must be installed and on PATH for the grep tool.
- MCP servers must be installed separately and runnable (stdio transport).
