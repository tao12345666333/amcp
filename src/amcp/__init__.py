"""AMCP - Lego-style Coding Agent CLI with Multi-Agent Support."""

__all__ = [
    "__version__",
    # Agent classes and functions
    "Agent",
    "AgentExecutionError",
    "MaxStepsReached",
    "BusyError",
    "create_agent_by_name",
    "create_agent_from_config",
    "create_subagent",
    "list_available_agents",
    "list_primary_agents",
    "list_subagent_types",
    # Multi-agent system
    "AgentMode",
    "AgentConfig",
    "AgentRegistry",
    "get_agent_registry",
    "get_agent_config",
    # Message queue
    "MessagePriority",
    "QueuedMessage",
    "MessageQueueManager",
    "get_message_queue_manager",
    # Event bus
    "Event",
    "EventBus",
    "EventType",
    "EventPriority",
    "get_event_bus",
    # Task system
    "Task",
    "TaskManager",
    "TaskState",
    "TaskPriority",
    "TaskTool",
    "get_task_manager",
]

__version__ = "0.3.0"

# Lazy imports for cleaner namespace
from .agent import (
    Agent,
    AgentExecutionError,
    BusyError,
    MaxStepsReached,
    create_agent_by_name,
    create_agent_from_config,
    create_subagent,
    list_available_agents,
    list_primary_agents,
    list_subagent_types,
)
from .event_bus import (
    Event,
    EventBus,
    EventPriority,
    EventType,
    get_event_bus,
)
from .message_queue import (
    MessagePriority,
    MessageQueueManager,
    QueuedMessage,
    get_message_queue_manager,
)
from .multi_agent import (
    AgentConfig,
    AgentMode,
    AgentRegistry,
    get_agent_config,
    get_agent_registry,
)
from .task import (
    Task,
    TaskManager,
    TaskPriority,
    TaskState,
    TaskTool,
    get_task_manager,
)
