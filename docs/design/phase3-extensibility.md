# AMCP Phase 3: Extensibility Features

This document describes the Phase 3 features implemented for AMCP: **Event Bus** and **Task Tool** for parallel sub-agent execution.

## Overview

Phase 3 focuses on extensibility, adding two major features:

1. **Event Bus** - A publish/subscribe event system for agent communication and plugin development
2. **Task Tool** - Support for spawning parallel sub-agents to execute tasks concurrently

## Event Bus

The Event Bus provides a centralized pub/sub system for agent events, enabling:

- **Monitoring**: Track tool executions, agent lifecycle, and errors
- **Plugins**: Build extensions that react to agent activities
- **Debugging**: Log and analyze agent behavior
- **Integration**: Connect AMCP to external systems

### Event Types

```python
from amcp import EventType

# Agent lifecycle
EventType.AGENT_STARTED     # Agent began processing
EventType.AGENT_COMPLETED   # Agent finished successfully
EventType.AGENT_ERROR       # Agent encountered an error
EventType.AGENT_STEP        # Agent completed a step

# Tool events
EventType.TOOL_STARTED      # Tool execution started
EventType.TOOL_COMPLETED    # Tool completed successfully
EventType.TOOL_ERROR        # Tool failed

# Task events (parallel sub-agents)
EventType.TASK_CREATED      # New task created
EventType.TASK_STARTED      # Task began executing
EventType.TASK_COMPLETED    # Task finished
EventType.TASK_FAILED       # Task failed
EventType.TASK_CANCELLED    # Task was cancelled

# Session events
EventType.SESSION_CREATED   # New session started
EventType.SESSION_BUSY      # Session became busy
EventType.SESSION_IDLE      # Session became idle

# System events
EventType.CONFIG_CHANGED    # Configuration changed
EventType.SHUTDOWN          # System shutting down
```

### Usage

#### Subscribing to Events

```python
from amcp import get_event_bus, Event, EventType

bus = get_event_bus()

# Using decorator
@bus.on(EventType.TOOL_COMPLETED)
async def on_tool_completed(event: Event):
    print(f"Tool {event.data['tool_name']} completed")
    print(f"Duration: {event.data.get('duration_ms')}ms")

# Manual subscription
def my_handler(event: Event):
    print(f"Event: {event.type.value}")

handler_id = bus.subscribe(
    event_types=EventType.AGENT_STARTED,
    callback=my_handler,
    priority=EventPriority.HIGH,
)

# Unsubscribe later
bus.unsubscribe(handler_id)
```

#### Publishing Events

```python
from amcp import get_event_bus, Event, EventType

bus = get_event_bus()

# Async emit
await bus.emit(Event(
    type=EventType.TOOL_COMPLETED,
    source="my_tool",
    session_id="session-123",
    data={
        "tool_name": "read_file",
        "result": "...",
        "duration_ms": 45.2,
    }
))

# Sync emit (fire and forget)
bus.emit_sync(Event(
    type=EventType.CUSTOM,
    data={"message": "Hello!"}
))
```

#### Handler Priority

```python
from amcp import EventPriority

# Handlers execute in priority order
bus.subscribe(EventType.CUSTOM, low_handler, priority=EventPriority.LOW)
bus.subscribe(EventType.CUSTOM, high_handler, priority=EventPriority.HIGH)
bus.subscribe(EventType.CUSTOM, critical_handler, priority=EventPriority.CRITICAL)

# Order: CRITICAL -> HIGH -> NORMAL -> LOW
```

#### Session Filtering

```python
# Only receive events from a specific session
bus.subscribe(
    event_types=EventType.TOOL_COMPLETED,
    callback=my_handler,
    session_filter="session-123",
)
```

#### One-time Handlers

```python
# Handler automatically removed after first call
bus.subscribe(
    event_types=EventType.AGENT_COMPLETED,
    callback=my_handler,
    once=True,
)
```

---

## Task Tool (Parallel Sub-Agents)

The Task Tool enables agents to spawn sub-agents that execute tasks in parallel.

### Why Use Tasks?

- **Speed**: Execute multiple independent operations concurrently
- **Focus**: Delegate specialized work to specialized agents
- **Efficiency**: Don't block on long-running operations

### Available Agent Types

| Agent Type | Mode | Max Steps | Best For |
|------------|------|-----------|----------|
| `explorer` | subagent | 50 | Fast read-only codebase exploration |
| `planner` | subagent | 30 | Analysis and planning |
| `focused_coder` | subagent | 100 | Specific implementation tasks |

### Agent Usage

When using AMCP, agents have access to the `task` tool:

```
Create a task to find all TODO comments in the codebase
```

The agent will use:
```json
{
  "action": "create",
  "description": "Find all TODO comments in the codebase",
  "agent_type": "explorer"
}
```

### Task Actions

#### Create a Task
```json
{
  "action": "create",
  "description": "Find all Python files using deprecated APIs",
  "agent_type": "explorer"
}
```

Returns:
```
Task created successfully!

Task ID: a1b2c3
Description: Find all Python files using deprecated APIs
Agent Type: explorer
State: pending

Use {"action": "wait", "task_id": "a1b2c3"} to wait for results.
```

#### Check Task Status
```json
{
  "action": "status",
  "task_id": "a1b2c3"
}
```

Returns:
```
Task ID: a1b2c3
Description: Find all Python files...
Agent Type: explorer
State: running
Started: 2024-01-15T10:30:00
Duration: 5234ms
```

#### Wait for Task Completion
```json
{
  "action": "wait",
  "task_id": "a1b2c3",
  "timeout": 60
}
```

Returns:
```
Task a1b2c3 completed successfully!

Duration: 8532ms

Result:
Found 15 files with deprecated APIs:
1. src/old_module.py - uses deprecated `asyncio.get_event_loop()`
2. ...
```

#### List All Tasks
```json
{
  "action": "list"
}
```

Returns:
```
Tasks:

✅ a1b2c3: Find all Python files using deprecated APIs...
   State: completed | Agent: explorer

🔄 d4e5f6: Refactor authentication module...
   State: running | Agent: focused_coder

⏳ g7h8i9: Generate API documentation...
   State: pending | Agent: planner

Total: 3 | Running: 1
```

#### Cancel a Task
```json
{
  "action": "cancel",
  "task_id": "d4e5f6"
}
```

### Programmatic Usage

```python
from amcp import get_task_manager, TaskPriority

manager = get_task_manager()

# Create tasks
task1 = await manager.create_task(
    description="Analyze project structure",
    agent_type="explorer",
    priority=TaskPriority.HIGH,
)

task2 = await manager.create_task(
    description="Find security vulnerabilities",
    agent_type="explorer",
)

# Wait for all tasks
results = await manager.wait_for_all([task1.id, task2.id])

for task in results:
    print(f"{task.id}: {task.result[:100]}...")

# Or wait for just the first one
first = await manager.wait_for_any([task1.id, task2.id])
print(f"First complete: {first.id}")
```

---

## Configuration

### Config File (`~/.config/amcp/config.toml`)

```toml
[chat]
# ... existing config ...

# Task settings
enable_task = true        # Enable task tool (default: true)
max_concurrent_tasks = 5  # Max parallel tasks (default: 5)
```

### CLI Options

```bash
# List available agent types for tasks
amcp --list-types

# Use a specific agent type
amcp -t explorer --once "Find all TODO comments"
```

---

## Event Flow Example

Here's how events flow during task execution:

```
1. TASK_CREATED
   └─ Task "Find TODOs" created with ID "abc123"

2. TASK_STARTED
   └─ Sub-agent "explorer" begins execution

3. TOOL_STARTED (in sub-agent)
   └─ explorer uses grep tool

4. TOOL_COMPLETED (in sub-agent)
   └─ grep found 15 matches

5. SUBAGENT_COMPLETED
   └─ explorer finished with result

6. TASK_COMPLETED
   └─ Task "abc123" completed successfully
```

---

## Integration Examples

### Logging All Tool Calls

```python
from amcp import get_event_bus, Event, EventType
import logging

logger = logging.getLogger("amcp.tools")

@get_event_bus().on(EventType.TOOL_COMPLETED)
async def log_tools(event: Event):
    logger.info(
        f"Tool: {event.data['tool_name']} | "
        f"Duration: {event.data.get('duration_ms', 0):.0f}ms | "
        f"Session: {event.session_id}"
    )
```

### Progress Tracking

```python
from amcp import get_event_bus, EventType

tasks_completed = 0
tasks_total = 0

@get_event_bus().on(EventType.TASK_CREATED)
async def on_created(event):
    global tasks_total
    tasks_total += 1
    print(f"Progress: {tasks_completed}/{tasks_total}")

@get_event_bus().on(EventType.TASK_COMPLETED)
async def on_completed(event):
    global tasks_completed
    tasks_completed += 1
    print(f"Progress: {tasks_completed}/{tasks_total}")
```

### Webhook Integration

```python
import httpx
from amcp import get_event_bus, EventType

@get_event_bus().on(EventType.AGENT_COMPLETED)
async def notify_webhook(event):
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://webhook.example.com/amcp",
            json={
                "event": event.type.value,
                "session_id": event.session_id,
                "result": event.data.get("result", "")[:500],
            }
        )
```

---

## Version

These features were added in **AMCP v0.3.0**.
