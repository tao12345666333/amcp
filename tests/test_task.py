"""Tests for the task module."""

import asyncio

import pytest

from amcp.task import (
    Task,
    TaskManager,
    TaskPriority,
    TaskState,
    TaskTool,
    get_task_manager,
    reset_task_manager,
)


@pytest.fixture
def task_manager():
    """Create a fresh task manager for each test."""
    return TaskManager(max_concurrent=2)


@pytest.fixture(autouse=True)
def reset_global_manager():
    """Reset global task manager before and after each test."""
    reset_task_manager()
    yield
    reset_task_manager()


class TestTaskState:
    """Tests for TaskState enum."""

    def test_state_values(self):
        """Test state values."""
        assert TaskState.PENDING.value == "pending"
        assert TaskState.RUNNING.value == "running"
        assert TaskState.COMPLETED.value == "completed"
        assert TaskState.FAILED.value == "failed"
        assert TaskState.CANCELLED.value == "cancelled"


class TestTaskPriority:
    """Tests for TaskPriority enum."""

    def test_priority_ordering(self):
        """Test priority values are ordered."""
        assert TaskPriority.LOW.value < TaskPriority.NORMAL.value
        assert TaskPriority.NORMAL.value < TaskPriority.HIGH.value
        assert TaskPriority.HIGH.value < TaskPriority.URGENT.value


class TestTask:
    """Tests for Task dataclass."""

    def test_create_task(self):
        """Test creating a task."""
        task = Task.create(
            description="Test task",
            agent_type="explorer",
            priority=TaskPriority.HIGH,
            parent_session_id="session-123",
        )
        assert task.description == "Test task"
        assert task.agent_type == "explorer"
        assert task.priority == TaskPriority.HIGH
        assert task.parent_session_id == "session-123"
        assert task.state == TaskState.PENDING
        assert task.id is not None

    def test_is_done(self):
        """Test is_done property."""
        task = Task.create("Test")

        task.state = TaskState.PENDING
        assert not task.is_done

        task.state = TaskState.RUNNING
        assert not task.is_done

        task.state = TaskState.COMPLETED
        assert task.is_done

        task.state = TaskState.FAILED
        assert task.is_done

        task.state = TaskState.CANCELLED
        assert task.is_done

    def test_to_dict(self):
        """Test converting task to dictionary."""
        task = Task.create("Test task", agent_type="explorer")
        d = task.to_dict()

        assert d["id"] == task.id
        assert d["description"] == "Test task"
        assert d["agent_type"] == "explorer"
        assert d["state"] == "pending"
        assert "created_at" in d


class TestTaskManager:
    """Tests for TaskManager class."""

    @pytest.mark.asyncio
    async def test_create_task(self, task_manager):
        """Test creating a task."""
        task = await task_manager.create_task(
            description="Test task",
            agent_type="explorer",
            auto_start=False,
        )
        assert task.description == "Test task"
        assert task.agent_type == "explorer"
        assert task.state == TaskState.PENDING

    @pytest.mark.asyncio
    async def test_create_task_invalid_agent(self, task_manager):
        """Test creating task with invalid agent type."""
        with pytest.raises(ValueError, match="Unknown agent type"):
            await task_manager.create_task(
                description="Test",
                agent_type="nonexistent",
                auto_start=False,
            )

    @pytest.mark.asyncio
    async def test_get_task(self, task_manager):
        """Test getting a task by ID."""
        task = await task_manager.create_task(
            description="Test",
            agent_type="explorer",
            auto_start=False,
        )
        retrieved = task_manager.get_task(task.id)
        assert retrieved is not None
        assert retrieved.id == task.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, task_manager):
        """Test getting a non-existent task."""
        assert task_manager.get_task("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_tasks(self, task_manager):
        """Test listing tasks."""
        await task_manager.create_task("Task 1", "explorer", auto_start=False)
        await task_manager.create_task("Task 2", "planner", auto_start=False)

        tasks = task_manager.list_tasks()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_list_tasks_by_state(self, task_manager):
        """Test filtering tasks by state."""
        task1 = await task_manager.create_task("Task 1", "explorer", auto_start=False)
        await task_manager.create_task("Task 2", "explorer", auto_start=False)

        # Manually set state for test
        task1.state = TaskState.COMPLETED

        pending = task_manager.list_tasks(state=TaskState.PENDING)
        assert len(pending) == 1

        completed = task_manager.list_tasks(state=TaskState.COMPLETED)
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_list_tasks_by_session(self, task_manager):
        """Test filtering tasks by session."""
        await task_manager.create_task("Task 1", "explorer", parent_session_id="s1", auto_start=False)
        await task_manager.create_task("Task 2", "explorer", parent_session_id="s2", auto_start=False)

        s1_tasks = task_manager.list_tasks(parent_session_id="s1")
        assert len(s1_tasks) == 1
        assert s1_tasks[0].parent_session_id == "s1"

    @pytest.mark.asyncio
    async def test_get_stats(self, task_manager):
        """Test getting statistics."""
        await task_manager.create_task("Task 1", "explorer", auto_start=False)
        await task_manager.create_task("Task 2", "explorer", auto_start=False)

        stats = task_manager.get_stats()
        assert stats["total_tasks"] == 2
        assert stats["by_state"]["pending"] == 2
        assert stats["max_concurrent"] == 2

    def test_get_pending_count(self, task_manager):
        """Test counting pending tasks."""
        assert task_manager.get_pending_count() == 0

    def test_get_running_count(self, task_manager):
        """Test counting running tasks."""
        assert task_manager.get_running_count() == 0


class TestTaskTool:
    """Tests for TaskTool class."""

    @pytest.fixture
    def tool(self):
        """Create a TaskTool instance."""
        return TaskTool(session_id="test-session")

    @pytest.mark.asyncio
    async def test_create_action(self, tool):
        """Test create action."""
        result = await tool.execute(
            action="create",
            description="Find all TODO comments",
            agent_type="explorer",
        )
        assert "Task created successfully" in result
        assert "Task ID:" in result

    @pytest.mark.asyncio
    async def test_create_missing_description(self, tool):
        """Test create action without description."""
        result = await tool.execute(action="create")
        assert "Error" in result
        assert "description" in result.lower()

    @pytest.mark.asyncio
    async def test_status_action(self, tool):
        """Test status action."""
        # Create a task first
        create_result = await tool.execute(
            action="create",
            description="Test task",
            agent_type="explorer",
        )
        # Extract task ID
        task_id = None
        for line in create_result.split("\n"):
            if "Task ID:" in line:
                task_id = line.split(":")[1].strip()
                break

        assert task_id is not None

        # Get status
        result = await tool.execute(action="status", task_id=task_id)
        assert task_id in result
        assert "Test task" in result

    @pytest.mark.asyncio
    async def test_status_missing_task_id(self, tool):
        """Test status action without task_id."""
        result = await tool.execute(action="status")
        assert "Error" in result
        assert "task_id" in result.lower()

    @pytest.mark.asyncio
    async def test_status_nonexistent_task(self, tool):
        """Test status for non-existent task."""
        result = await tool.execute(action="status", task_id="nonexistent")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_list_action(self, tool):
        """Test list action."""
        # Create some tasks
        await tool.execute(
            action="create",
            description="Task 1",
            agent_type="explorer",
        )
        await tool.execute(
            action="create",
            description="Task 2",
            agent_type="explorer",
        )

        result = await tool.execute(action="list")
        assert "Task 1" in result or "Tasks:" in result

    @pytest.mark.asyncio
    async def test_list_empty(self, tool):
        """Test list action with no tasks."""
        # Use a different session so it's empty
        tool2 = TaskTool(session_id="empty-session")
        result = await tool2.execute(action="list")
        # Should not error, may show "No tasks" or empty list
        assert result is not None

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool):
        """Test unknown action."""
        result = await tool.execute(action="unknown")
        assert "Unknown action" in result

    @pytest.mark.asyncio
    async def test_cancel_missing_task_id(self, tool):
        """Test cancel action without task_id."""
        result = await tool.execute(action="cancel")
        assert "Error" in result


class TestGlobalTaskManager:
    """Tests for global task manager singleton."""

    def test_singleton(self):
        """Test that get_task_manager returns a singleton."""
        manager1 = get_task_manager()
        manager2 = get_task_manager()
        assert manager1 is manager2

    def test_reset(self):
        """Test resetting global task manager."""
        manager1 = get_task_manager()
        reset_task_manager()
        manager2 = get_task_manager()
        assert manager1 is not manager2
