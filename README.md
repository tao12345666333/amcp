# AMCP

[![PyPI version](https://badge.fury.io/py/amcp-agent.svg)](https://badge.fury.io/py/amcp-agent)
[![CI](https://github.com/tao12345666333/amcp/workflows/CI/badge.svg)](https://github.com/tao12345666333/amcp/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Deploy your own on GMI Cloud](https://img.shields.io/badge/Deploy%20your%20own-GMI%20Cloud-ddea4d)](https://console.gmicloud.ai/user-console/ie/agentbox/browse-agents/amcp-agent)

New to GMI Cloud? [Create an account with my referral link](https://console.gmicloud.ai/ref/KP3NWZV4).

**An out-of-the-box coding-agent runtime for your terminal, IDE, server, and Telegram.**

AMCP is built for developers who want a useful agent immediately, not a framework they must
assemble first. It ships with file editing, shell execution, web access, memory, skills,
subagents, MCP/ACP integration, hooks, remote server mode, Telegram control, and scheduled
automation as first-class capabilities.

Use it as a local coding assistant, an IDE agent, a long-running remote worker, or the runtime
behind your own agent workflows.

## Why AMCP

- **Ready on the first run**: read/search/edit files, apply patches, run commands, browse the web,
  keep todos, and remember project context without installing a pile of plugins.
- **One runtime, many surfaces**: use the same sessions from the CLI, ACP-compatible IDEs such as
  Zed, an HTTP/WebSocket server, Telegram, or cron/systemd/Kubernetes jobs.
- **Autonomous but inspectable**: persistent sessions, request-scoped tool limits, context
  compaction, progress events, and cancellation support make long-running work easier to trust.
- **Extensible when you need it**: add MCP servers, skills, slash commands, hooks, and custom agent
  specs without giving up the built-in experience.

## 30-second start

```bash
# Configure your model provider interactively
uvx amcp-agent init

# Start the coding agent in the current project
uvx amcp-agent

# Or run a single task
uvx amcp-agent --once "summarize this repository and suggest the next test to run"
```

## What you get

| Area | Built-in capabilities |
|------|-----------------------|
| **Coding loop** | `read_file`, `grep`, `apply_patch`, `write_file`, `bash`, `think`, `todo`, `task` |
| **Research** | Web search/fetch tools plus MCP server integration over stdio or HTTP/SSE |
| **Agent orchestration** | Primary/subagent architecture with `coder`, `explorer`, `planner`, and `focused_coder` types |
| **Context & memory** | Persistent sessions, AGENTS.md rules, smart compaction, progressive loading, searchable memory and session history |
| **Interfaces** | CLI, ACP for IDEs, FastAPI HTTP/WebSocket server, Telegram bot |
| **Customization** | TOML config, YAML agent specs, slash commands, reusable skills, hooks, event bus |
| **Model support** | OpenAI Chat Completions, OpenAI Responses API, Anthropic Claude, and OpenAI-compatible endpoints |

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

# Using uv (recommended); includes dependencies needed by the full test suite
uv sync --extra dev --extra telegram
source .venv/bin/activate

# Or with pip in an activated virtual environment
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev,telegram]"
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
amcp mcp tools --server custom
amcp mcp call --server custom --tool example_tool --args '{"query":"rust async"}'

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
| **web_search** | Search the web for information without configuring a search API key |
| **web_fetch** | Fetch and extract content from web pages without configuring a search API key |
| **memory** | Store and retrieve persistent cross-session memories |
| **session_search** | Search persisted conversation history across sessions |

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

## Memory System

AMCP maintains persistent cross-session context using complementary memory layers:
- **MEMORY.md**: Curated long-term facts, preferences, and knowledge
- **HISTORY.md**: Append-only activity and decision history
- **memory.db**: Durable facts and episodic events with SQLite FTS5 search
- **SOUL.md / IDENTITY.md**: Optional global persona and identity guidance

Memory is stored at:
- User-level: `~/.config/amcp/memory/`
- Project-level: `.amcp/memory/` (project-specific knowledge)
- Global persona: `~/.config/amcp/SOUL.md` and `~/.config/amcp/IDENTITY.md`

The `memory` tool manages durable knowledge, while `session_search` searches persisted
conversation history. User and project memory are merged for context; persona files remain
global so the agent keeps one identity across interfaces and projects.

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
active_provider = "primary"    # optional: selected [chat.providers.<name>] profile
mcp_tools_enabled = true
write_tool_enabled = true
edit_tool_enabled = true
tool_loop_limit = 300
bash_tool_limit = 100
default_max_lines = 400
read_roots = ["."]                # optional: restrict read_file to these roots
default_agent = "coder"        # optional: coder, explorer, planner, focused_coder
max_queue_size = 100

[chat.providers.primary]
api_type = "openai"
base_url = "https://example.com/v1"
model = "provider/model-name"

[chat.providers.backup]
api_type = "anthropic"
model = "claude-model-name"
```

Telegram can switch configured providers without calling the LLM:

- `/models` lists configured provider profiles.
- `/model use backup` switches `active_provider` and persists it to `config.toml` (admin only).

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
[servers.custom]
url = "https://example.com/mcp"

# stdio transport
[servers.local]
command = "npx"
args = ["-y", "@some/mcp-server"]
```

Configured MCP servers are exposed as `mcp.<server>.<tool>` tools. The built-in
`web_search` and `web_fetch` tools are available separately and work out of the
box without adding a search MCP server.

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

## Development

### Setup

```bash
uv sync --extra dev --extra telegram
source .venv/bin/activate
uv tool install pre-commit
pre-commit install

# Or use pip in an activated virtual environment
python -m pip install -e ".[dev,telegram]"
python -m pip install pre-commit
pre-commit install
```

### Running Tests

```bash
make test          # run all tests
make test-cov      # run with coverage
python -m pytest -q -m "not llm"  # CI-equivalent suite without live provider calls
python -m pytest tests/test_tools.py -v  # specific test
```

### Code Quality

```bash
make lint          # ruff check
make format        # ruff format
make type-check    # mypy
```

CI runs Ruff and the non-`llm` test suite on Python 3.11, 3.12, and 3.13. Tests marked `llm`
call live model providers and require credentials.

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed development guidelines.

## Notes

- `rg` (ripgrep) must be installed and on PATH for the grep tool.
- MCP servers must be installed separately and runnable (stdio transport).
- The agent does not add an application-level retry around model provider failures; provider client behavior applies.
- Tool-call guardrails include per-request `bash` limits, output truncation for `bash`, and
  per-conversation plus per-session `read_file` limits.

## License

Apache-2.0
