# AMCP

[![PyPI version](https://badge.fury.io/py/amcp-agent.svg)](https://badge.fury.io/py/amcp-agent)
[![CI](https://github.com/tao12345666333/amcp/workflows/CI/badge.svg)](https://github.com/tao12345666333/amcp/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A Lego-style coding agent CLI with built-in tools (grep, read files, bash execution, web search/fetch) and MCP server integration for extended capabilities.

## Features

- **Built-in Tools**: read_file, grep, bash, think, todo, apply_patch, write_file, task, web_search, web_fetch, memory
- **MCP Integration**: Connect to any MCP server (stdio or HTTP/SSE transport) for extended capabilities
- **Multi-LLM Support**: OpenAI Chat Completions, OpenAI Responses API, Anthropic Claude, and any OpenAI-compatible endpoint
- **Multi-Agent System**: Primary/Subagent architecture with built-in agent types (coder, explorer, planner, focused_coder)
- **Skills System**: Reusable knowledge/behavior definitions with auto-trigger, scheduling, and hot reload
- **Slash Commands**: Custom command shortcuts with shell injection (`!{...}`) and file injection (`@{...}`)
- **Conversation History**: Persistent sessions across runs
- **Flexible Configuration**: YAML-based agent specifications and TOML config
- **ACP Support**: Full Agent Client Protocol support for IDE integration (Zed, etc.)
- **AGENTS.md Support**: Auto-load project-specific rules from `AGENTS.md` files
- **Smart Context Compaction**: Intelligent context management with dynamic thresholds
- **Progressive Context View**: Dynamic tool and skill loading based on relevance scoring and context budget
- **Memory System**: Persistent cross-session memory (MEMORY.md + HISTORY.md) at user and project levels
- **Event Bus**: Publish/subscribe system for agent communication and extensibility
- **Hooks System**: Extensible hooks for tool validation, logging, and custom behaviors
- **HTTP/WebSocket Server**: Remote access via FastAPI with session management and live events
- **Telegram Bot Integration**: Remote interaction with DM/group support, pairing, and notifications
- **Automation/Cron Jobs**: Scheduled task execution for external orchestrators (systemd, cron, K8s)
- **Toad TUI**: Terminal UI support via the `tui` command (requires Python 3.14+)
- **Model Database**: Model metadata from models.dev for context window and output limit resolution

## Installation

### Quick Run with uvx (no install needed)

```bash
# Initialize config first (model and runtime settings)
uvx amcp-agent init

# Run the agent
uvx amcp-agent

# Run as ACP server (for IDE integration)
uvx amcp-agent acp serve
```

### From PyPI

```bash
pip install amcp-agent

# With Anthropic Claude support
pip install amcp-agent[anthropic]

# With Telegram bot support
pip install amcp-agent[telegram]
```

### From Source (development)

```bash
git clone https://github.com/tao12345666333/amcp.git
cd amcp

# using uv (recommended)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# or with pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
# Initialize config
amcp init              # interactive wizard
amcp init --quick      # default config without prompts

# Agent chat (default command)
amcp                                    # interactive mode with conversation history
amcp --once "create a hello.py file"    # single message
amcp -t explorer --once "find all TODOs"  # use built-in agent type
amcp --agent path/to/agent.yaml         # use custom agent spec
amcp --session my-session               # use specific session ID
amcp --clear                            # clear conversation history
amcp --list                             # list available agent specifications
amcp --list-types                       # list built-in agent types
amcp --list-sessions                    # list saved sessions

# MCP server management
amcp mcp tools --server exa
amcp mcp call --server exa --tool web_search_exa --args '{"query":"rust async"}'

# ACP (IDE integration)
amcp acp serve                          # start ACP agent server (stdio)
amcp acp info                           # show ACP configuration info

# HTTP/WebSocket server
amcp serve                              # start on localhost:4096
amcp serve --port 8080 --host 0.0.0.0   # custom host/port
amcp serve --telegram                   # start Telegram bot alongside
amcp attach http://localhost:4096       # connect to a running server

# Telegram bot
amcp telegram start                     # start polling
amcp telegram status                    # show config status
amcp telegram setup                     # interactive setup

# Automation / cron jobs
amcp cron list                          # list scheduled jobs
amcp cron add                           # add a new job
amcp cron run <job-name>                # run a job immediately
amcp cron enable <job-name>             # enable a job
amcp cron disable <job-name>            # disable a job

# Toad TUI (Python 3.14+)
amcp tui                                # launch terminal UI
```

## Built-in Tools

| Tool | Description |
|------|-------------|
| **read_file** | Read text files with slice mode (line ranges) or indentation mode (anchor-based context) |
| **grep** | Search for patterns in files using ripgrep |
| **bash** | Execute shell commands from the request working directory; large output is truncated |
| **think** | Internal reasoning and planning |
| **todo** | Manage a todo list to track tasks during complex operations |
| **apply_patch** | Apply diff-based patches to files (see [docs/apply-patch.md](docs/apply-patch.md)) |
| **write_file** | Write content to files (for creating new small files) |
| **task** | Spawn sub-agents for parallel task execution |
| **web_search** | Search the web for information |
| **web_fetch** | Fetch and extract content from web pages |
| **memory** | Store and retrieve persistent cross-session memories |

## Multi-Agent System

AMCP supports a Primary/Subagent architecture with built-in agent types:

| Agent Type | Mode | Description |
|------------|------|-------------|
| **coder** | Primary | Full-capability coding agent with write access |
| **explorer** | Subagent | Read-only fast codebase exploration |
| **planner** | Subagent | Read-only planning and analysis |
| **focused_coder** | Subagent | Focused implementation of specific changes |

Primary agents can delegate to subagents for complex tasks. Use `-t <type>` to select an agent type.

## Skills System

Skills are reusable knowledge or behavior definitions (markdown with YAML frontmatter) that inject specialized capabilities into the agent's system prompt. See [docs/skills-and-commands.md](docs/skills-and-commands.md) for full documentation.

**Built-in skills:**
- `skill-creator` - Generate new skills interactively
- `session-cleanup` - Clean up old session files
- `heartbeat` - Periodic health check and status reporting
- `networked-research` - Multi-source web research with synthesis
- `telegram-sender` - Send messages via Telegram

**Discovery locations (increasing precedence):**
1. Built-in skills (bundled with AMCP)
2. User skills: `~/.config/amcp/skills/<name>/SKILL.md`
3. Home agent skills: `~/.agents/skills/<name>/SKILL.md`
4. Project skills: `.amcp/skills/<name>/SKILL.md`

Skills support scheduled (cron) and event-based auto-triggers for autonomous execution. Hot reload is enabled when running the HTTP server.

## Slash Commands

Custom command shortcuts defined as TOML files, invoked with `/command` syntax. Features include:
- `{{args}}` placeholder for command arguments
- `!{shell command}` for shell output injection (auto-escaped args)
- `@{file path}` for file content injection
- Namespaced commands via subdirectories (e.g., `git/commit.toml` -> `/git:commit`)

**Discovery locations:**
1. User commands: `~/.config/amcp/commands/*.toml`
2. Project commands: `.amcp/commands/*.toml` (takes precedence)

See [docs/skills-and-commands.md](docs/skills-and-commands.md) for details and [examples/commands/](examples/commands/) for samples.

## ACP (Agent Client Protocol) Support

AMCP fully supports the [Agent Client Protocol](https://agentclientprotocol.com/) for integration with IDEs like Zed.

### Features

- **Session Management**: Create, load, and list sessions
- **Session Modes**: `ask` (request permission), `architect` (plan only), `code` (full tool access)
- **Slash Commands**: `/clear`, `/plan`, `/search`, `/help`
- **Agent Plans**: Visual execution plans for complex tasks
- **Permission Requests**: User approval for sensitive operations
- **Client Capabilities**: Use client's filesystem and terminal when available

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
          "command": "amcp",
          "args": ["acp", "serve"]
        }
      }
    },
    "default_profile": "amcp"
  }
}
```

## HTTP/WebSocket Server

AMCP can run as an HTTP/WebSocket server for remote access:

```bash
amcp serve                    # start on localhost:4096
amcp serve --port 8080        # custom port
amcp serve -w /path/to/project  # set working directory
amcp attach http://localhost:4096  # connect from another terminal
```

**API endpoints** (visit `/docs` for interactive Swagger UI):
- `GET /api/v1/health` - health check
- `POST /api/v1/sessions` - create sessions
- `POST /api/v1/sessions/{id}/prompt` - submit a prompt and return request status
- `POST /api/v1/sessions/{id}/prompt/stream` - submit a prompt and stream JSON-line events
- `POST /api/v1/sessions/{id}/cancel` - cancel current session work
- `DELETE /api/v1/sessions/{id}` - delete a session
- `GET /api/v1/tools` - list available tools
- `GET /api/v1/agents` - list agent types
- `WS /ws` - WebSocket for live events

Supports CORS configuration and optional server-side authentication.

## Telegram Integration

AMCP provides a Telegram Bot interface for remote interaction with agents. Install with `pip install amcp-agent[telegram]`.

**Features:**
- DM and group chat support with configurable policies (allowlist, mention, open, disabled)
- Pairing via one-time codes
- Topic/thread support in group chats
- Notification system (CI failures, PR reviews, task completions, error alerts)
- Webhook and polling modes
- Rate limiting, session timeout, typing indicators, and bounded per-session queues
- Shared slash commands including `/new`, `/session list`, `/session switch <id>`, `/clear`, and `/cancel`
- `/new` creates a fresh session and abandons the previous Telegram session's active work and queued messages

Configure via `amcp telegram setup` or in `config.toml` under `[telegram]`.

## Automation / Cron Jobs

AMCP supports scheduled automation jobs designed for external orchestrators (systemd, cron, K8s):

```bash
amcp cron list                # list configured jobs
amcp cron add                 # add a new job interactively
amcp cron run ci-check        # execute a job once
amcp cron enable ci-check     # enable a job
amcp cron disable ci-check    # disable a job
```

Jobs are defined in `config.toml` under `[automation.jobs]` and can reference skills or custom prompts with cron schedules.

## Memory System

AMCP maintains persistent cross-session memory using a two-layer approach:
- **MEMORY.md**: Long-term facts, preferences, and knowledge (curated, compact)
- **HISTORY.md**: Append-only searchable log of past activities

Memory is stored at:
- User-level: `~/.config/amcp/memory/`
- Project-level: `.amcp/memory/` (project-specific knowledge)

The agent uses the `memory` tool to store and retrieve memories, enabling self-evolution by accumulating knowledge over time.

## Hooks System

AMCP provides a flexible hooks system to extend and customize agent behavior. Hooks can:
- Validate and modify tool inputs before execution
- Process tool outputs after execution
- Block dangerous operations
- Log and audit agent activities

Create `.amcp/hooks.toml` in your project:

```toml
[hooks.PreToolUse]
[[hooks.PreToolUse.handlers]]
matcher = "write_file|apply_patch"
type = "python"
script = "./scripts/validate-writes.py"
timeout = 30

[[hooks.PostToolUse.handlers]]
matcher = "*"
type = "command"
command = "echo 'Tool executed' >> /tmp/tool_log.txt"
```

See [docs/hooks.md](docs/hooks.md) for full documentation.

## Config

The CLI loads configuration from `~/.config/amcp/config.toml`. Generate a starter config:

```bash
amcp init
```

### Chat Configuration

```toml
[chat]
api_type = "openai"            # "openai" (default), "openai_responses", or "anthropic"
base_url = "https://example.com/v1"
model = "provider/model-name"
mcp_tools_enabled = true
write_tool_enabled = true
edit_tool_enabled = true
tool_loop_limit = 300
default_max_lines = 400
default_agent = "coder"        # optional: coder, explorer, planner, focused_coder
max_queue_size = 100
```

**Anthropic Claude:**
```toml
[chat]
api_type = "anthropic"
model = "claude-model-name"
```

Install with: `pip install amcp-agent[anthropic]`

### MCP Servers

```toml
# HTTP/SSE transport
[servers.exa]
url = "https://mcp.exa.ai/mcp"

# stdio transport
[servers.custom]
command = "npx"
args = ["-y", "@some/mcp-server"]
```

### Context Optimization

```toml
[context]
progressive_tools = true       # dynamically load tools based on relevance
progressive_skills = true      # dynamically load skills based on relevance
response_ratio = 0.30          # reserve 30% of context for response
```

### Server Configuration

```toml
[server]
host = "127.0.0.1"
port = 4096
```

### Telegram Configuration

```toml
[telegram]
enabled = false
allowed_users = [123456789]
admin_users = [123456789]
dm_policy = "allowlist"        # "allowlist", "pairing", "open", "disabled"
group_policy = "mention"       # "mention", "open", "allowlist", "disabled"
max_queue_size = 20
typing_indicator = true

[telegram.pairing]
enabled = true
code_ttl_seconds = 1800
```

The Telegram runtime also supports group-specific and topic-specific policy overrides under
`[telegram.groups."<chat_id>"]` and `[telegram.groups."<chat_id>".topics."<topic_id>"]`.

### Automation Configuration

```toml
[automation]
enabled = true
default_timeout = 300

[[automation.jobs]]
name = "ci-check"
command = "Run tests and lint checks"
schedule = "0 9 * * 1-5"       # weekdays at 9 AM
enabled = true
timeout = 600
```

## Development

### Setup

```bash
pip install -e ".[dev]"
pre-commit install
```

### Running Tests

```bash
make test          # run all tests
make test-cov      # run with coverage
pytest tests/test_tools.py -v  # specific test
```

### Code Quality

```bash
make lint          # ruff check
make format        # ruff format
make type-check    # mypy
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed development guidelines.

## Notes

- `rg` (ripgrep) must be installed and on PATH for the grep tool.
- MCP servers must be installed separately and runnable (stdio transport).
- The agent does not add an application-level retry around model provider failures; provider client behavior applies.
- Tool-call guardrails include per-request `bash` limits, output truncation for `bash`, and session-level `read_file` limits.

## License

Apache-2.0
