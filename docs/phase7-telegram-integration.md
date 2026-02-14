# AMCP Phase 7: Telegram Integration

Remote interaction channel for AMCP via Telegram Bot API, enabling users to command, monitor, and receive notifications from their agent on any device.

## Motivation

Currently, AMCP can only be accessed via the local terminal CLI or by connecting to the HTTP/WebSocket server. This limits interaction to devices with direct access. Telegram integration provides:

- **Remote access**: Command your agent from your phone, tablet, or any device with Telegram
- **Asynchronous interaction**: Send tasks and check results at your convenience
- **Notification channel**: Receive proactive alerts (CI failures, PR reviews, scheduled task results)
- **Foundation for autonomy**: When combined with Heartbeat + Cron (Phase 8), enables fully autonomous operation with human-in-the-loop oversight

## Architecture

### High-Level Design

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│   Telegram   │────▶│  TelegramClient  │────▶│    Agent     │
│   Bot API    │◀────│  (Transport)     │◀────│   (Core)     │
└──────────────┘     └──────────────────┘     └──────────────┘
                              │                      │
                              ▼                      ▼
                     ┌──────────────────┐     ┌──────────────┐
                     │  Message Queue   │     │   Memory     │
                     │  (Rate Limiting) │     │   System     │
                     └──────────────────┘     └──────────────┘
```

### Component Breakdown

```
src/amcp/
├── telegram/
│   ├── __init__.py
│   ├── bot.py           # TelegramBot: main bot lifecycle
│   ├── client.py        # TelegramClient: implements BaseClient interface
│   ├── handlers.py      # Message, command, and callback handlers
│   ├── formatter.py     # Rich text → Telegram MarkdownV2 conversion
│   └── auth.py          # User authentication and authorization
```

### Integration Points

The Telegram module integrates with existing AMCP subsystems:

| AMCP Component | Integration |
|----------------|-------------|
| **Agent** | Executes prompts, returns responses |
| **Memory** | Logs Telegram conversations to history |
| **Skills** | Lists and activates skills via commands |
| **Event Bus** | Subscribes to events for proactive notifications |
| **Config** | Reads bot token, allowed users from config.toml |

## Configuration

### Config File (`~/.config/amcp/config.toml`)

```toml
[telegram]
enabled = true
bot_token = "BOT_TOKEN_HERE"          # From @BotFather
allowed_users = [123456789]           # Telegram user IDs (whitelist)
admin_users = [123456789]             # Users with admin privileges
webhook_mode = false                  # true for webhook, false for polling
webhook_url = ""                      # Required if webhook_mode = true
max_message_length = 4096             # Telegram message limit
rate_limit_messages = 20              # Max messages per minute per user
session_timeout = 3600                # Session timeout in seconds

[telegram.notifications]
ci_failures = true                    # Notify on CI failures
pr_reviews = true                     # Notify on PR review requests
task_completions = true               # Notify on async task completions
error_alerts = true                   # Notify on agent errors
```

### Environment Variables (Alternative)

```bash
export AMCP_TELEGRAM_BOT_TOKEN="..."
export AMCP_TELEGRAM_ALLOWED_USERS="123456789,987654321"
```

## Bot Commands

### Core Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Initialize bot, show welcome message | `/start` |
| `/help` | List available commands | `/help` |
| `/status` | Show agent status, active sessions | `/status` |
| `/session` | Manage sessions (new, list, switch) | `/session new` |
| `/cancel` | Cancel current operation | `/cancel` |

### Agent Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/ask <prompt>` | Send a prompt (alternative to plain text) | `/ask find all TODO comments` |
| `/skills` | List available skills | `/skills` |
| `/activate <skill>` | Activate a skill | `/activate gh-code-review` |
| `/memory` | View/search memory | `/memory search ruff` |

### Admin Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/config` | View/update configuration | `/config show` |
| `/users` | Manage allowed users | `/users add 123456789` |
| `/logs` | View recent agent logs | `/logs 20` |
| `/shutdown` | Gracefully stop the agent | `/shutdown` |

## Message Flow

### Incoming Messages (User → Agent)

```
1. Telegram API delivers update to TelegramBot
2. AuthMiddleware checks user ID against allowed_users
3. Handler routes message:
   - /command → CommandHandler
   - Plain text → PromptHandler
   - File/Photo → AttachmentHandler (future)
4. PromptHandler creates/reuses session
5. Agent.run() processes the prompt
6. Response is formatted (Markdown → Telegram MarkdownV2)
7. Long responses are split into multiple messages (≤4096 chars)
8. Response sent back via Telegram API
```

### Outgoing Notifications (Agent → User)

```
1. Event Bus emits event (e.g., TASK_COMPLETED)
2. NotificationHandler receives event
3. Handler checks notification preferences
4. Formats notification message
5. Sends to all subscribed users via Telegram API
```

## Implementation Details

### TelegramBot (Core)

```python
from amcp.telegram.bot import TelegramBot

bot = TelegramBot(
    token="BOT_TOKEN",
    allowed_users={123456789},
    agent_factory=lambda: Agent(spec),
)

# Start with polling (development)
await bot.start_polling()

# Or start with webhook (production)
await bot.start_webhook(url="https://example.com/webhook")
```

### TelegramClient (BaseClient Implementation)

```python
from amcp.client.base import BaseClient

class TelegramClient(BaseClient):
    """Telegram as an AMCP client transport."""

    async def connect(self) -> None:
        """Start the Telegram bot."""
        await self.bot.start_polling()

    async def prompt(self, session_id, content, *, stream=True, **kwargs):
        """Send prompt to agent, return response."""
        result = await self.agent.run(content, work_dir=self.work_dir)
        return result

    async def close(self) -> None:
        """Stop the Telegram bot."""
        await self.bot.stop()
```

### Response Formatting

Telegram has specific MarkdownV2 formatting requirements. The formatter handles:

```python
class TelegramFormatter:
    """Convert agent output to Telegram-compatible format."""

    def format_response(self, text: str) -> list[str]:
        """Convert markdown to Telegram MarkdownV2 and split into chunks."""
        # 1. Escape special characters for MarkdownV2
        # 2. Convert code blocks (```lang → pre tags)
        # 3. Convert inline code (` → monospace)
        # 4. Split into ≤4096 char chunks at natural boundaries
        ...

    def format_error(self, error: str) -> str:
        """Format error message with warning emoji."""
        return f"⚠️ *Error*: {self._escape(error)}"

    def format_tool_call(self, tool_name: str, result: str) -> str:
        """Format tool execution result."""
        return f"🔧 `{tool_name}`\n{result[:500]}"
```

### Session Management

Each Telegram chat maps to an AMCP session:

```python
class SessionManager:
    """Map Telegram chats to AMCP sessions."""

    def __init__(self):
        self._sessions: dict[int, str] = {}  # chat_id → session_id

    def get_or_create_session(self, chat_id: int) -> str:
        """Get existing session or create new one for a chat."""
        if chat_id not in self._sessions:
            self._sessions[chat_id] = f"telegram-{chat_id}-{uuid4().hex[:8]}"
        return self._sessions[chat_id]
```

### Authentication

```python
class AuthMiddleware:
    """Authenticate Telegram users."""

    def __init__(self, allowed_users: set[int], admin_users: set[int]):
        self.allowed_users = allowed_users
        self.admin_users = admin_users

    def is_authorized(self, user_id: int) -> bool:
        return user_id in self.allowed_users

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_users
```

## CLI Integration

### Start Telegram Bot

```bash
# Start as standalone Telegram bot
amcp telegram start

# Start with specific config
amcp telegram start --token "BOT_TOKEN" --allow-user 123456789

# Start alongside HTTP server
amcp serve --telegram

# Check bot status
amcp telegram status
```

### Setup Wizard

```bash
# Interactive setup
amcp telegram setup
# Guides user through:
# 1. Creating bot via @BotFather
# 2. Getting bot token
# 3. Finding user ID (via @userinfobot)
# 4. Saving to config.toml
```

## Security Considerations

1. **User Whitelist**: Only explicitly allowed user IDs can interact with the bot
2. **Admin Separation**: Destructive operations (config, shutdown) require admin role
3. **Token Storage**: Bot token stored in config.toml with restricted file permissions (0600)
4. **Rate Limiting**: Per-user rate limits to prevent abuse
5. **No Sensitive Data in Logs**: Bot token and user messages are not logged verbatim
6. **Session Isolation**: Each Telegram user gets their own isolated session

## Dependencies

```toml
[project.optional-dependencies]
telegram = [
    "python-telegram-bot>=21.0",    # Async Telegram Bot API wrapper
]
```

Install with:
```bash
pip install amcp[telegram]
# or
uv pip install amcp[telegram]
```

## Event Bus Integration

The Telegram bot subscribes to events for proactive notifications:

```python
from amcp import get_event_bus, EventType

@get_event_bus().on(EventType.TASK_COMPLETED)
async def notify_task_complete(event):
    """Send Telegram notification when a task completes."""
    await bot.send_notification(
        f"✅ Task completed: {event.data['description']}\n"
        f"Duration: {event.data['duration_ms']}ms\n"
        f"Result: {event.data['result'][:500]}"
    )

@get_event_bus().on(EventType.AGENT_ERROR)
async def notify_error(event):
    """Send Telegram notification on agent errors."""
    await bot.send_notification(
        f"🚨 Agent Error\n"
        f"Session: {event.session_id}\n"
        f"Error: {event.data['error'][:500]}"
    )
```

## Memory Integration

Telegram conversations are automatically logged to the memory system:

```python
# After each Telegram interaction:
memory_mgr.append_history(
    content=f"[Telegram] User: {user_message[:200]}\nAgent: {response[:300]}",
    session_id=session_id,
    tags=["telegram", "conversation"],
    scope="project",
)
```

## Example Interaction

```
User: /start
Bot:  👋 Welcome to AMCP Bot!

      I'm your AI coding agent. Send me any message
      and I'll help you with your project.

      Available commands:
      /help - Show all commands
      /status - Check agent status
      /skills - List available skills

User: Check if there are any failing CI jobs in the repo

Bot:  🔧 Using `bash` tool...

      ✅ I checked the CI status using `gh run list`:

      • Run #42: ✅ Passed (main, 2m ago)
      • Run #41: ✅ Passed (feat/memory-system, 5m ago)

      All CI jobs are passing! 🎉

User: /skills

Bot:  📚 Available Skills:
      • skill-creator - Create new AMCP skills
      • gh-code-review - GitHub PR code review
      • gh-ci-analyzer - CI log analysis

      Use /activate <name> to enable a skill.

User: /memory search "ruff"

Bot:  🔍 Found 4 results for "ruff":
      1. Fixed ruff UP042 lint errors across 3 files
      2. Lint with ruff check - failed step
      3. Code formatting issue (ruff linting errors)
      4. Fixed ruff UP042 lint errors...
```

## Testing Strategy

1. **Unit Tests**: Mock Telegram API, test handlers, formatters, auth
2. **Integration Tests**: Test with real bot token against Telegram test server
3. **E2E Tests**: Full flow from Telegram message → Agent → Response

```python
# tests/test_telegram.py
class TestTelegramFormatter:
    def test_escape_special_characters(self): ...
    def test_split_long_messages(self): ...
    def test_code_block_formatting(self): ...

class TestAuthMiddleware:
    def test_authorized_user(self): ...
    def test_unauthorized_user(self): ...
    def test_admin_user(self): ...

class TestSessionManager:
    def test_create_session(self): ...
    def test_reuse_session(self): ...
    def test_session_timeout(self): ...
```

## Rollout Plan

1. **Phase 7a**: Core bot with polling mode, basic prompt/response
2. **Phase 7b**: Commands, skill activation, memory access
3. **Phase 7c**: Event-based notifications, webhook mode
4. **Phase 7d**: File/image handling, inline keyboards

## Version

Telegram Integration is planned for **AMCP v0.10.0**.
