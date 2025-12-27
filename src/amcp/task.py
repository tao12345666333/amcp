"""
Task Tool - Parallel Sub-Agent Execution for AMCP.

This module provides task management capabilities that allow the main agent
to spawn sub-agents for parallel task execution, inspired by OpenCode's
task system.

Key Features:
- Create and manage parallel tasks (sub-agents)
- Track task status and results
- Support for task dependencies
- Cancellation support
- Event-driven task lifecycle
- Resource limits per task

Task States:
- PENDING: Task created but not started
- RUNNING: Task is executing
- COMPLETED: Task finished successfully
- FAILED: Task failed with an error
- CANCELLED: Task was cancelled

Example:
    from amcp.task import TaskManager, get_task_manager

    manager = get_task_manager()

    # Create a task
    task = await manager.create_task(
        description="Analyze the codebase structure",
        agent_type="explorer",
        parent_session_id="main-session",
    )

    # Wait for completion
    result = await manager.wait_for_task(task.id)
    print(result.result)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .event_bus import (
    EventType,
    emit_task_event,
)
from .multi_agent import AgentMode, create_subagent_config, get_agent_registry

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """States a task can be in."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Priority levels for task execution."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


@dataclass
class Task:
    """A task that can be executed by a sub-agent.

    Attributes:
        id: Unique task identifier
        description: Human-readable task description
        agent_type: Type of agent to use (e.g., "explorer", "focused_coder")
        state: Current task state
        priority: Task priority
        parent_session_id: Parent session that created this task
        created_at: When the task was created
        started_at: When execution started
        completed_at: When execution completed
        result: Task result (if completed)
        error: Error message (if failed)
        metadata: Additional task metadata
    """

    id: str
    description: str
    agent_type: str
    state: TaskState = TaskState.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    parent_session_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _future: asyncio.Future | None = field(default=None, repr=False)
    _task: asyncio.Task | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        description: str,
        agent_type: str = "focused_coder",
        priority: TaskPriority = TaskPriority.NORMAL,
        parent_session_id: str | None = None,
        **metadata: Any,
    ) -> Task:
        """Create a new task.

        Args:
            description: Task description
            agent_type: Type of agent to use
            priority: Task priority
            parent_session_id: Parent session ID
            **metadata: Additional metadata

        Returns:
            New Task instance
        """
        return cls(
            id=str(uuid.uuid4())[:8],
            description=description,
            agent_type=agent_type,
            priority=priority,
            parent_session_id=parent_session_id,
            metadata=metadata,
        )

    @property
    def is_done(self) -> bool:
        """Check if task is in a terminal state."""
        return self.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED)

    @property
    def duration_ms(self) -> float | None:
        """Get task duration in milliseconds."""
        if self.started_at is None:
            return None
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds() * 1000

    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary representation."""
        return {
            "id": self.id,
            "description": self.description,
            "agent_type": self.agent_type,
            "state": self.state.value,
            "priority": self.priority.value,
            "parent_session_id": self.parent_session_id,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class TaskManager:
    """Manages task creation, execution, and lifecycle.

    The TaskManager allows spawning sub-agents to execute tasks in parallel,
    with support for priorities, cancellation, and status tracking.

    Example:
        manager = TaskManager()

        # Create multiple tasks
        task1 = await manager.create_task("Find all TODO comments", "explorer")
        task2 = await manager.create_task("Analyze dependencies", "planner")

        # Wait for all tasks
        results = await manager.wait_for_all([task1.id, task2.id])

        # Or wait for any task
        first_result = await manager.wait_for_any([task1.id, task2.id])
    """

    def __init__(self, max_concurrent: int = 5):
        """Initialize the task manager.

        Args:
            max_concurrent: Maximum number of concurrent tasks
        """
        self._tasks: dict[str, Task] = {}
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        description: str,
        agent_type: str = "focused_coder",
        priority: TaskPriority = TaskPriority.NORMAL,
        parent_session_id: str | None = None,
        auto_start: bool = True,
        **metadata: Any,
    ) -> Task:
        """Create a new task.

        Args:
            description: Task description
            agent_type: Type of agent to use
            priority: Task priority
            parent_session_id: Parent session ID
            auto_start: Whether to start the task immediately
            **metadata: Additional metadata

        Returns:
            The created Task
        """
        # Validate agent type
        registry = get_agent_registry()
        if agent_type not in registry.list_agents():
            available = ", ".join(registry.list_agents())
            raise ValueError(f"Unknown agent type: {agent_type}. Available: {available}")

        # Create task
        task = Task.create(
            description=description,
            agent_type=agent_type,
            priority=priority,
            parent_session_id=parent_session_id,
            **metadata,
        )

        async with self._lock:
            self._tasks[task.id] = task

        # Emit event
        await emit_task_event(
            EventType.TASK_CREATED,
            task.id,
            description,
            parent_session_id,
            agent_type=agent_type,
            priority=priority.value,
        )

        logger.info(f"Created task {task.id}: {description[:50]}...")

        if auto_start:
            await self.start_task(task.id)

        return task

    async def start_task(self, task_id: str) -> None:
        """Start executing a task.

        Args:
            task_id: ID of the task to start
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        if task.state != TaskState.PENDING:
            raise ValueError(f"Task {task_id} is not pending (state: {task.state})")

        # Create future for result
        loop = asyncio.get_event_loop()
        task._future = loop.create_future()

        # Start execution in background
        task._task = asyncio.create_task(self._execute_task(task))

        logger.info(f"Started task {task_id}")

    async def _execute_task(self, task: Task) -> None:
        """Execute a task using a sub-agent.

        Args:
            task: The task to execute
        """
        # Acquire semaphore for concurrency limiting
        async with self._semaphore:
            task.state = TaskState.RUNNING
            task.started_at = datetime.now()

            await emit_task_event(
                EventType.TASK_STARTED,
                task.id,
                task.description,
                task.parent_session_id,
            )

            try:
                # Import here to avoid circular imports
                from .agent import create_agent_from_config

                # Get agent config
                registry = get_agent_registry()
                config = registry.get(task.agent_type)

                if config is None:
                    # Create a custom subagent config
                    config = create_subagent_config(
                        parent_name="task_manager",
                        task_description=task.description,
                    )

                # Ensure it's a subagent
                if config.mode == AgentMode.PRIMARY:
                    # Use focused_coder for primary agents to limit scope
                    config = registry.get("focused_coder") or config

                # Create agent
                agent = create_agent_from_config(config)

                # Execute the task
                result = await agent.run(
                    user_input=task.description,
                    stream=False,
                    show_progress=False,
                )

                # Mark completed
                task.state = TaskState.COMPLETED
                task.completed_at = datetime.now()
                task.result = result

                await emit_task_event(
                    EventType.TASK_COMPLETED,
                    task.id,
                    task.description,
                    task.parent_session_id,
                    result=result[:500] if result else None,
                    duration_ms=task.duration_ms,
                )

                logger.info(f"Completed task {task.id} in {task.duration_ms:.0f}ms")

                # Set future result
                if task._future and not task._future.done():
                    task._future.set_result(task)

            except asyncio.CancelledError:
                task.state = TaskState.CANCELLED
                task.completed_at = datetime.now()
                task.error = "Task was cancelled"

                await emit_task_event(
                    EventType.TASK_CANCELLED,
                    task.id,
                    task.description,
                    task.parent_session_id,
                )

                logger.info(f"Cancelled task {task.id}")

                if task._future and not task._future.done():
                    task._future.cancel()

            except Exception as e:
                task.state = TaskState.FAILED
                task.completed_at = datetime.now()
                task.error = str(e)

                await emit_task_event(
                    EventType.TASK_FAILED,
                    task.id,
                    task.description,
                    task.parent_session_id,
                    error=str(e),
                )

                logger.error(f"Task {task.id} failed: {e}")

                if task._future and not task._future.done():
                    task._future.set_exception(e)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task.

        Args:
            task_id: ID of the task to cancel

        Returns:
            True if task was cancelled
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False

        if task.state != TaskState.RUNNING:
            return False

        if task._task is not None:
            task._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task._task
            return True

        return False

    async def wait_for_task(self, task_id: str, timeout: float | None = None) -> Task:
        """Wait for a task to complete.

        Args:
            task_id: ID of the task to wait for
            timeout: Maximum time to wait (None = infinite)

        Returns:
            The completed task

        Raises:
            ValueError: If task not found
            asyncio.TimeoutError: If timeout exceeded
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        if task.is_done:
            return task

        if task._future is None:
            raise ValueError(f"Task {task_id} was never started")

        if timeout is not None:
            await asyncio.wait_for(task._future, timeout)
        else:
            await task._future

        return task

    async def wait_for_all(
        self,
        task_ids: list[str],
        timeout: float | None = None,
    ) -> list[Task]:
        """Wait for multiple tasks to complete.

        Args:
            task_ids: IDs of tasks to wait for
            timeout: Maximum time to wait

        Returns:
            List of completed tasks
        """
        futures = []
        for task_id in task_ids:
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            if task._future:
                futures.append(task._future)

        if futures:
            if timeout is not None:
                await asyncio.wait_for(
                    asyncio.gather(*futures, return_exceptions=True),
                    timeout,
                )
            else:
                await asyncio.gather(*futures, return_exceptions=True)

        return [self._tasks[tid] for tid in task_ids]

    async def wait_for_any(
        self,
        task_ids: list[str],
        timeout: float | None = None,
    ) -> Task:
        """Wait for any task to complete.

        Args:
            task_ids: IDs of tasks to wait for
            timeout: Maximum time to wait

        Returns:
            The first completed task
        """
        futures = []
        future_to_task: dict[asyncio.Future, str] = {}

        for task_id in task_ids:
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            if task._future:
                futures.append(task._future)
                future_to_task[task._future] = task_id

        if not futures:
            raise ValueError("No running tasks to wait for")

        done, _ = await asyncio.wait(
            futures,
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if not done:
            raise TimeoutError("No task completed within timeout")

        first_future = next(iter(done))
        task_id = future_to_task[first_future]
        return self._tasks[task_id]

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        state: TaskState | None = None,
        parent_session_id: str | None = None,
    ) -> list[Task]:
        """List tasks with optional filtering.

        Args:
            state: Filter by state
            parent_session_id: Filter by parent session

        Returns:
            List of matching tasks
        """
        tasks = list(self._tasks.values())

        if state is not None:
            tasks = [t for t in tasks if t.state == state]

        if parent_session_id is not None:
            tasks = [t for t in tasks if t.parent_session_id == parent_session_id]

        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def get_pending_count(self) -> int:
        """Get number of pending tasks."""
        return sum(1 for t in self._tasks.values() if t.state == TaskState.PENDING)

    def get_running_count(self) -> int:
        """Get number of running tasks."""
        return sum(1 for t in self._tasks.values() if t.state == TaskState.RUNNING)

    async def cleanup_completed(self, max_age_seconds: float = 3600) -> int:
        """Remove old completed tasks.

        Args:
            max_age_seconds: Maximum age of completed tasks to keep

        Returns:
            Number of tasks removed
        """
        now = datetime.now()
        to_remove = []

        async with self._lock:
            for task_id, task in self._tasks.items():
                if task.is_done and task.completed_at:
                    age = (now - task.completed_at).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(task_id)

            for task_id in to_remove:
                del self._tasks[task_id]

        return len(to_remove)

    def get_stats(self) -> dict[str, Any]:
        """Get task manager statistics."""
        by_state = {}
        for state in TaskState:
            by_state[state.value] = sum(1 for t in self._tasks.values() if t.state == state)

        return {
            "total_tasks": len(self._tasks),
            "by_state": by_state,
            "max_concurrent": self._max_concurrent,
            "available_slots": self._semaphore._value,
        }


# Global task manager singleton
_task_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    """Get the global task manager instance.

    Returns:
        Global TaskManager singleton
    """
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager


def reset_task_manager() -> None:
    """Reset the global task manager (mainly for testing)."""
    global _task_manager
    _task_manager = None


# TaskTool implementation for agent use


class TaskTool:
    """Tool for agents to spawn and manage parallel sub-tasks.

    This tool allows agents to delegate work to sub-agents that run in parallel.

    Tool Schema:
        {
            "name": "task",
            "description": "Spawn and manage parallel sub-agent tasks",
            "parameters": {
                "action": "create|status|wait|cancel|list",
                "description": "Task description (for create)",
                "agent_type": "Agent type to use (for create)",
                "task_id": "Task ID (for status/wait/cancel)",
                "timeout": "Timeout in seconds (for wait)"
            }
        }
    """

    name = "task"
    description = """Spawn and manage parallel sub-agent tasks.

Actions:
- create: Create a new task for a sub-agent to execute
- status: Check the status of a task
- wait: Wait for a task to complete
- cancel: Cancel a running task
- list: List all tasks

Agent Types:
- explorer: Read-only codebase exploration (fast)
- planner: Analysis and planning (read-only)
- focused_coder: Specific implementation tasks

Example:
    {"action": "create", "description": "Find all TODO comments", "agent_type": "explorer"}
    {"action": "status", "task_id": "abc123"}
    {"action": "wait", "task_id": "abc123", "timeout": 60}
"""

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "status", "wait", "cancel", "list"],
                "description": "Action to perform",
            },
            "description": {
                "type": "string",
                "description": "Task description (required for create)",
            },
            "agent_type": {
                "type": "string",
                "enum": ["explorer", "planner", "focused_coder"],
                "description": "Agent type for the task (default: focused_coder)",
            },
            "task_id": {
                "type": "string",
                "description": "Task ID (required for status/wait/cancel)",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds for wait action",
            },
        },
        "required": ["action"],
    }

    def __init__(self, session_id: str | None = None):
        """Initialize TaskTool.

        Args:
            session_id: Session ID for tracking parent tasks
        """
        self.session_id = session_id
        self._manager = get_task_manager()

    async def execute(self, **kwargs: Any) -> str:
        """Execute the task tool.

        Args:
            **kwargs: Tool arguments

        Returns:
            Result as a string
        """
        action = kwargs.get("action")

        if action == "create":
            return await self._create_task(**kwargs)
        elif action == "status":
            return await self._get_status(**kwargs)
        elif action == "wait":
            return await self._wait_for_task(**kwargs)
        elif action == "cancel":
            return await self._cancel_task(**kwargs)
        elif action == "list":
            return await self._list_tasks(**kwargs)
        else:
            return f"Unknown action: {action}. Valid actions: create, status, wait, cancel, list"

    async def _create_task(self, **kwargs: Any) -> str:
        """Create a new task."""
        description = kwargs.get("description")
        if not description:
            return "Error: 'description' is required for create action"

        agent_type = kwargs.get("agent_type", "focused_coder")

        try:
            task = await self._manager.create_task(
                description=description,
                agent_type=agent_type,
                parent_session_id=self.session_id,
            )
            return f"""Task created successfully!

Task ID: {task.id}
Description: {task.description}
Agent Type: {task.agent_type}
State: {task.state.value}

Use {{"action": "wait", "task_id": "{task.id}"}} to wait for results.
Use {{"action": "status", "task_id": "{task.id}"}} to check status."""

        except Exception as e:
            return f"Error creating task: {e}"

    async def _get_status(self, **kwargs: Any) -> str:
        """Get task status."""
        task_id = kwargs.get("task_id")
        if not task_id:
            return "Error: 'task_id' is required for status action"

        task = self._manager.get_task(task_id)
        if task is None:
            return f"Task not found: {task_id}"

        status_lines = [
            f"Task ID: {task.id}",
            f"Description: {task.description}",
            f"Agent Type: {task.agent_type}",
            f"State: {task.state.value}",
            f"Created: {task.created_at.isoformat()}",
        ]

        if task.started_at:
            status_lines.append(f"Started: {task.started_at.isoformat()}")

        if task.completed_at:
            status_lines.append(f"Completed: {task.completed_at.isoformat()}")

        if task.duration_ms:
            status_lines.append(f"Duration: {task.duration_ms:.0f}ms")

        if task.result:
            # Truncate long results
            result_preview = task.result[:500] + "..." if len(task.result) > 500 else task.result
            status_lines.append(f"\nResult:\n{result_preview}")

        if task.error:
            status_lines.append(f"\nError: {task.error}")

        return "\n".join(status_lines)

    async def _wait_for_task(self, **kwargs: Any) -> str:
        """Wait for a task to complete."""
        task_id = kwargs.get("task_id")
        if not task_id:
            return "Error: 'task_id' is required for wait action"

        timeout = kwargs.get("timeout")

        try:
            task = await self._manager.wait_for_task(task_id, timeout)

            if task.state == TaskState.COMPLETED:
                return f"""Task {task.id} completed successfully!

Duration: {task.duration_ms:.0f}ms

Result:
{task.result}"""
            elif task.state == TaskState.FAILED:
                return f"Task {task.id} failed: {task.error}"
            elif task.state == TaskState.CANCELLED:
                return f"Task {task.id} was cancelled"
            else:
                return f"Task {task.id} is {task.state.value}"

        except TimeoutError:
            return f"Timeout waiting for task {task_id}"
        except Exception as e:
            return f"Error waiting for task: {e}"

    async def _cancel_task(self, **kwargs: Any) -> str:
        """Cancel a task."""
        task_id = kwargs.get("task_id")
        if not task_id:
            return "Error: 'task_id' is required for cancel action"

        success = await self._manager.cancel_task(task_id)
        if success:
            return f"Task {task_id} cancelled successfully"
        else:
            return f"Could not cancel task {task_id} (may not be running)"

    async def _list_tasks(self, **kwargs: Any) -> str:
        """List all tasks."""
        tasks = self._manager.list_tasks(parent_session_id=self.session_id)

        if not tasks:
            return "No tasks found."

        lines = ["Tasks:"]
        for task in tasks:
            state_emoji = {
                TaskState.PENDING: "⏳",
                TaskState.RUNNING: "🔄",
                TaskState.COMPLETED: "✅",
                TaskState.FAILED: "❌",
                TaskState.CANCELLED: "🚫",
            }.get(task.state, "❓")

            lines.append(f"\n{state_emoji} {task.id}: {task.description[:50]}...")
            lines.append(f"   State: {task.state.value} | Agent: {task.agent_type}")

        stats = self._manager.get_stats()
        lines.append(f"\nTotal: {stats['total_tasks']} | Running: {stats['by_state']['running']}")

        return "\n".join(lines)


def get_task_tool_schema() -> dict[str, Any]:
    """Get the JSON schema for the task tool."""
    return {
        "type": "function",
        "function": {
            "name": TaskTool.name,
            "description": TaskTool.description,
            "parameters": TaskTool.parameters,
        },
    }
