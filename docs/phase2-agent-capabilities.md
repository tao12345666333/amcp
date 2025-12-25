# AMCP Phase 2: Agent Capabilities

This document describes the new multi-agent and message queue capabilities added to AMCP.

## Overview

Two major features have been added:

1. **Multi-Agent Configuration** - Support for different agent types (PRIMARY/SUBAGENT)
2. **Message Queue** - Session-level message queuing for concurrent handling

---

## 1. Multi-Agent System (`multi_agent.py`)

### AgentMode Enum

Defines two agent execution modes:

```python
class AgentMode(Enum):
    PRIMARY = "primary"    # Main agents with full capabilities
    SUBAGENT = "subagent"  # Task-specific agents with restricted capabilities
```

### AgentConfig

Configuration for agent types:

```python
@dataclass
class AgentConfig:
    name: str                    # Unique identifier
    mode: AgentMode              # PRIMARY or SUBAGENT
    description: str             # Human-readable description
    system_prompt: str           # System prompt template
    tools: list[str]             # Allowed tools (empty = all)
    excluded_tools: list[str]    # Explicitly disabled tools
    max_steps: int               # Maximum execution steps
    can_delegate: bool           # Can spawn subagents
    parent_agent: str | None     # Parent agent name (for subagents)
```

### Built-in Agents

| Agent | Mode | Description | Tools |
|-------|------|-------------|-------|
| `coder` | PRIMARY | Main coding agent with full capabilities | All |
| `explorer` | SUBAGENT | Fast read-only codebase exploration | read_file, grep, glob, think |
| `planner` | SUBAGENT | Analysis and planning (read-only) | read_file, grep, glob, think |
| `focused_coder` | SUBAGENT | Focused implementation tasks | read_file, grep, write_file, edit_file, bash, think |

### Usage

```python
from amcp import (
    AgentMode,
    AgentConfig,
    get_agent_registry,
    create_agent_by_name,
    list_available_agents,
)

# List available agents
print(list_available_agents())  # ['coder', 'explorer', 'planner', 'focused_coder']

# Create agent by name
agent = create_agent_by_name('coder')
print(agent.agent_spec.mode)  # AgentMode.PRIMARY

# Create subagent
explorer = create_agent_by_name('explorer')
print(explorer.agent_spec.can_delegate)  # False

# Register custom agent
registry = get_agent_registry()
custom = AgentConfig(
    name="my_agent",
    mode=AgentMode.PRIMARY,
    description="Custom agent",
    system_prompt="You are a custom agent...",
    tools=["read_file", "grep"],
    excluded_tools=[],
    max_steps=100,
)
registry.register(custom)
```

---

## 2. Message Queue System (`message_queue.py`)

### Core Concepts

- **Session-specific queues**: Each session has its own message queue
- **Priority support**: Messages can have LOW, NORMAL, HIGH, or URGENT priority
- **Busy state tracking**: Prevents concurrent processing of the same session
- **Automatic queue processing**: Queued messages are processed when session becomes free

### MessagePriority

```python
class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3
```

### QueuedMessage

```python
@dataclass
class QueuedMessage:
    id: str
    session_id: str
    prompt: str
    attachments: list[dict]
    priority: MessagePriority
    created_at: datetime
    metadata: dict
```

### MessageQueueManager

```python
from amcp import get_message_queue_manager, MessagePriority

manager = get_message_queue_manager()

# Check if session is busy
if manager.is_busy("session-123"):
    # Queue the message
    await manager.enqueue("session-123", "Hello!", priority=MessagePriority.HIGH)
else:
    # Acquire the session
    acquired = await manager.acquire("session-123")
    try:
        # Process message
        result = await process_message()
    finally:
        manager.release("session-123")

# Check queue status
status = manager.get_queue_status("session-123")
print(status)
# {'session_id': 'session-123', 'is_busy': False, 'queued_count': 1, 'queued_prompts': ['Hello!']}
```

### Integration with Agent

The Agent class now automatically integrates with the message queue:

```python
from amcp import create_agent_by_name, MessagePriority

agent = create_agent_by_name('coder')

# Run with automatic queuing
result = await agent.run(
    "Write a function",
    priority=MessagePriority.NORMAL,
    queue_if_busy=True,  # Queue if session is busy
)

# Check queue status
print(agent.is_busy())       # False
print(agent.queued_count())  # 0
print(agent.get_queue_status())

# Clear queued messages
await agent.clear_queue()
```

---

## 3. Updated Agent Class

### New Methods

```python
class Agent:
    # Queue-related methods
    def is_busy(self) -> bool
    def queued_count(self) -> int
    def queued_prompts(self) -> list[str]
    async def clear_queue(self) -> int
    def get_queue_status(self) -> dict

    # Updated run method
    async def run(
        self,
        user_input: str,
        work_dir: Path | None = None,
        stream: bool = True,
        show_progress: bool = True,
        priority: MessagePriority = MessagePriority.NORMAL,
        queue_if_busy: bool = True,
    ) -> str
```

### New Exceptions

```python
class BusyError(Exception):
    """Raised when agent session is busy and queue_if_busy is False."""
    pass
```

### Factory Functions

```python
from amcp import (
    create_agent_by_name,
    create_agent_from_config,
    create_subagent,
    list_available_agents,
    list_primary_agents,
    list_subagent_types,
)

# Create by name
agent = create_agent_by_name('coder')

# Create from config
config = AgentConfig(...)
agent = create_agent_from_config(config)

# Create subagent for a task
subagent = create_subagent(
    parent_agent=agent,
    task_description="Analyze the codebase",
    tools=["read_file", "grep"],
)
```

---

## 4. Updated Agent Spec

The `ResolvedAgentSpec` now includes:

```python
@dataclass
class ResolvedAgentSpec:
    name: str
    description: str
    mode: AgentMode          # NEW: PRIMARY or SUBAGENT
    system_prompt: str
    tools: list[str]
    exclude_tools: list[str]
    max_steps: int
    model: str
    base_url: str
    can_delegate: bool       # NEW: Whether agent can spawn subagents
```

---

## Example: Multi-Agent Workflow

```python
import asyncio
from amcp import (
    create_agent_by_name,
    create_subagent,
    MessagePriority,
)

async def main():
    # Create main agent
    main_agent = create_agent_by_name('coder')
    
    # Run main task
    result = await main_agent.run("Analyze this codebase and suggest improvements")
    
    # If main agent can delegate, create a subagent for exploration
    if main_agent.agent_spec.can_delegate:
        explorer = create_subagent(
            parent_agent=main_agent,
            task_description="Find all TODO comments in the codebase",
            tools=["read_file", "grep"],
        )
        findings = await explorer.run("Find all TODO comments")
        print(f"Explorer found: {findings}")

asyncio.run(main())
```

---

## Comparison with Other Projects

| Feature | AMCP (Now) | OpenCode | Crush | Kimi-CLI |
|---------|------------|----------|-------|----------|
| Multi-agent modes | ✅ PRIMARY/SUBAGENT | ✅ | ✅ | ✅ |
| Message queue | ✅ | ❌ | ✅ | ❌ |
| Priority queuing | ✅ | ❌ | ❌ | ❌ |
| Subagent creation | ✅ | ✅ | ✅ | ✅ |
| Agent registry | ✅ | ✅ | ✅ | ✅ |
| Busy state tracking | ✅ | ❌ | ✅ | ❌ |
