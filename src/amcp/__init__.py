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
    # Smart compaction
    "SmartCompactor",
    "CompactionConfig",
    "CompactionStrategy",
    "CompactionResult",
    "get_model_context_window",
    "estimate_tokens",
    "create_compactor",
    # Models database
    "ModelsDatabase",
    "ModelInfo",
    "ProviderInfo",
    "get_models_database",
    "get_context_window_from_database",
    # Config
    "AMCPConfig",
    "ChatConfig",
    "ModelConfig",
    # Project rules
    "ProjectRulesLoader",
    "load_project_rules",
    "get_project_rules_info",
    # Hooks system
    "HookEvent",
    "HookDecision",
    "HookInput",
    "HookOutput",
    "HookHandler",
    "HooksManager",
    "get_hooks_manager",
    "run_pre_tool_use_hooks",
    "run_post_tool_use_hooks",
    "run_user_prompt_hooks",
    "run_session_start_hooks",
    "run_session_end_hooks",
    "run_stop_hooks",
    "run_pre_compact_hooks",
]

__version__ = "0.5.0"

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
from .compaction import (
    CompactionConfig,
    CompactionResult,
    CompactionStrategy,
    SmartCompactor,
    create_compactor,
    estimate_tokens,
    get_model_context_window,
)
from .config import (
    AMCPConfig,
    ChatConfig,
    ModelConfig,
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
from .models_db import (
    ModelInfo,
    ModelsDatabase,
    ProviderInfo,
    get_context_window_from_database,
    get_models_database,
)
from .multi_agent import (
    AgentConfig,
    AgentMode,
    AgentRegistry,
    get_agent_config,
    get_agent_registry,
)
from .project_rules import (
    ProjectRulesLoader,
    get_project_rules_info,
    load_project_rules,
)
from .task import (
    Task,
    TaskManager,
    TaskPriority,
    TaskState,
    TaskTool,
    get_task_manager,
)
from .hooks import (
    HookDecision,
    HookEvent,
    HookHandler,
    HookInput,
    HookOutput,
    HooksManager,
    get_hooks_manager,
    run_post_tool_use_hooks,
    run_pre_compact_hooks,
    run_pre_tool_use_hooks,
    run_session_end_hooks,
    run_session_start_hooks,
    run_stop_hooks,
    run_user_prompt_hooks,
)
