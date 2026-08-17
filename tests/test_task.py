"""Tests for the task module."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from ankaloop.task import (
    DelegationEnvelope,
    Task,
    TaskManager,
    TaskPriority,
    TaskState,
    TaskTool,
)


@pytest.fixture
def task_manager():
    """Create a fresh task manager for each test."""
    return TaskManager(max_concurrent=2)


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

    @pytest.mark.asyncio
    async def test_cancel_pending_task_prevents_later_execution(self):
        """A task waiting for a semaphore slot must never run after cancellation."""
        manager = TaskManager(max_concurrent=1)
        release = asyncio.Event()
        started = asyncio.Event()
        agents = []

        class FakeAgent:
            def __init__(self, config=None, *, ephemeral=False):
                self.closed = False
                assert ephemeral
                agents.append(self)

            async def run(self, **kwargs):
                started.set()
                await release.wait()
                return "done"

            async def close(self):
                self.closed = True

        with patch("ankaloop.agent.create_agent_from_config", side_effect=FakeAgent):
            first = await manager.create_task("first", "explorer")
            await started.wait()
            second = await manager.create_task("second", "explorer")

            assert second.state == TaskState.PENDING
            assert await manager.cancel_task(second.id)
            release.set()
            await manager.wait_for_task(first.id)
            await asyncio.sleep(0)

        assert second.state == TaskState.CANCELLED
        assert len(agents) == 1
        assert agents[0].closed

    @pytest.mark.asyncio
    async def test_wait_timeout_does_not_cancel_shared_completion(self):
        """A waiter timeout must not corrupt completion for later waiters."""
        manager = TaskManager(max_concurrent=1)
        release = asyncio.Event()

        class FakeAgent:
            async def run(self, **kwargs):
                await release.wait()
                return "done"

            async def close(self):
                pass

        with patch("ankaloop.agent.create_agent_from_config", return_value=FakeAgent()):
            task = await manager.create_task("slow", "explorer")
            with pytest.raises(TimeoutError):
                await manager.wait_for_task(task.id, timeout=0.01)

            assert task._future is not None
            assert not task._future.cancelled()
            release.set()
            completed = await manager.wait_for_task(task.id, timeout=1)

        assert completed.state == TaskState.COMPLETED
        assert completed.result == "done"

    @pytest.mark.asyncio
    async def test_failed_task_resolves_with_terminal_state(self):
        """Task failures should not poison the shared completion future."""
        manager = TaskManager(max_concurrent=1)

        class FakeAgent:
            async def run(self, **kwargs):
                raise RuntimeError("boom")

            async def close(self):
                pass

        with patch("ankaloop.agent.create_agent_from_config", return_value=FakeAgent()):
            task = await manager.create_task("fail", "explorer")
            completed = await manager.wait_for_task(task.id, timeout=1)

        assert completed.state == TaskState.FAILED
        assert completed.error == "boom"

    @pytest.mark.asyncio
    async def test_subagent_inherits_work_dir_and_is_closed(self, tmp_path):
        """Sub-agents run in the parent's trusted workspace and always close."""
        manager = TaskManager(max_concurrent=1)
        observed_work_dir = None
        closed = False

        class FakeAgent:
            async def run(self, **kwargs):
                nonlocal observed_work_dir
                observed_work_dir = kwargs["work_dir"]
                return "done"

            async def close(self):
                nonlocal closed
                closed = True

        with patch("ankaloop.agent.create_agent_from_config", return_value=FakeAgent()):
            task = await manager.create_task(
                "work",
                "explorer",
                work_dir=Path(tmp_path),
            )
            await manager.wait_for_task(task.id, timeout=1)

        assert observed_work_dir == tmp_path.resolve()
        assert closed

    @pytest.mark.asyncio
    async def test_cancellation_waits_for_subagent_close(self):
        """Cancellation settles sub-agent cleanup before completing waiters."""
        manager = TaskManager(max_concurrent=1)
        running = asyncio.Event()
        close_started = asyncio.Event()
        release_close = asyncio.Event()

        class FakeAgent:
            session_id = "fake-session"

            async def run(self, **kwargs):
                running.set()
                await asyncio.Event().wait()

            async def close(self):
                close_started.set()
                await release_close.wait()

        with patch("ankaloop.agent.create_agent_from_config", return_value=FakeAgent()):
            task = await manager.create_task("cancel", "explorer")
            await running.wait()
            cancellation = asyncio.create_task(manager.cancel_task(task.id))
            await close_started.wait()

            waiter = asyncio.create_task(manager.wait_for_task(task.id))
            await asyncio.sleep(0)
            assert not cancellation.done()
            assert not waiter.done()

            release_close.set()
            assert await cancellation
            completed = await waiter

        assert completed.state == TaskState.CANCELLED

    @pytest.mark.asyncio
    async def test_terminal_task_retention_is_bounded(self):
        """Old terminal task results are evicted from the in-memory manager."""
        manager = TaskManager(max_concurrent=1, max_terminal_tasks=2)

        class FakeAgent:
            async def run(self, **kwargs):
                return "done"

            async def close(self):
                pass

        with patch(
            "ankaloop.agent.create_agent_from_config",
            side_effect=lambda config, *, ephemeral: FakeAgent(),
        ):
            tasks = []
            for description in ("one", "two", "three"):
                task = await manager.create_task(description, "explorer")
                await manager.wait_for_task(task.id, timeout=1)
                tasks.append(task)

        assert manager.get_task(tasks[0].id) is None
        assert manager.get_task(tasks[1].id) is tasks[1]
        assert manager.get_task(tasks[2].id) is tasks[2]

    @pytest.mark.asyncio
    async def test_wait_for_any_survives_immediate_terminal_eviction(self):
        """A waiter keeps its task reference when retention is disabled."""
        manager = TaskManager(max_concurrent=1, max_terminal_tasks=0)
        release = asyncio.Event()

        class FakeAgent:
            session_id = "fake-session"

            async def run(self, **kwargs):
                await release.wait()
                return "done"

            async def close(self):
                pass

        with patch("ankaloop.agent.create_agent_from_config", return_value=FakeAgent()):
            task = await manager.create_task("evict", "explorer")
            waiter = asyncio.create_task(manager.wait_for_any([task.id], timeout=1))
            await asyncio.sleep(0)
            release.set()
            completed = await waiter

        assert completed is task
        assert completed.state == TaskState.COMPLETED
        assert manager.get_task(task.id) is None


class TestTaskTool:
    """Tests for TaskTool class."""

    @pytest.fixture
    def tool(self, task_manager):
        """Create a TaskTool instance."""
        return TaskTool(manager=task_manager, session_id="test-session")

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
    async def test_structured_envelope_is_rendered_and_runtime_workspace_is_trusted(self, tmp_path):
        """Only envelope fields reach the prompt; workspace remains runtime-owned."""
        manager = TaskManager(max_concurrent=1)
        tool = TaskTool(manager=manager, session_id="parent", work_dir=tmp_path)
        observed = {}

        class FakeAgent:
            async def run(self, **kwargs):
                observed.update(kwargs)
                return "done"

            async def close(self):
                observed["closed"] = True

        def create_agent(_config, *, ephemeral):
            observed["ephemeral"] = ephemeral
            return FakeAgent()

        envelope = {
            "goal": "Implement the parser",
            "known_context": "Failure occurs for empty input.",
            "relevant_files": ["src/parser.py"],
            "constraints": ["Do not change the public API"],
            "validation_required": ["pytest tests/test_parser.py"],
            "expected_return_shape": "Summary and test result",
        }
        with patch("ankaloop.agent.create_agent_from_config", side_effect=create_agent):
            result = await tool.execute(
                action="create",
                envelope=envelope,
                agent_type="focused_coder",
                work_dir="/untrusted/model/path",
            )
            task_id = next(line.split(":", 1)[1].strip() for line in result.splitlines() if "Task ID:" in line)
            task = await manager.wait_for_task(task_id, timeout=1)

        assert observed["ephemeral"] is True
        assert observed["work_dir"] == tmp_path.resolve()
        assert observed["closed"] is True
        assert (
            observed["user_input"]
            == """# Delegated task

## Goal
Implement the parser

## Known context / evidence
Failure occurs for empty input.

## Relevant files
- src/parser.py

## Constraints / non-goals
- Do not change the public API

## Validation required
- pytest tests/test_parser.py

## Expected return shape
Summary and test result"""
        )
        assert "/untrusted/model/path" not in observed["user_input"]
        assert task.work_dir == tmp_path.resolve()

    def test_legacy_description_maps_to_envelope_goal(self):
        """Existing description-only callers retain their task meaning."""
        task = Task.create("Inspect the code", agent_type="explorer")

        assert task.envelope == DelegationEnvelope(goal="Inspect the code")
        assert task.envelope.render() == "# Delegated task\n\n## Goal\nInspect the code"

        direct = Task("task-id", "Inspect the code", "explorer")
        assert direct.envelope == DelegationEnvelope(goal="Inspect the code")

    @pytest.mark.asyncio
    async def test_invalid_structured_envelope_is_rejected(self, tool):
        """Runtime validation matches the schema rather than dropping malformed context."""
        malformed = await tool.execute(
            action="create",
            envelope={"goal": "Inspect", "relevant_files": "src/parser.py"},
        )
        unknown = await tool.execute(
            action="create",
            envelope={"goal": "Inspect", "work_dir": "/untrusted"},
        )

        assert malformed == "Error: 'envelope.relevant_files' must be an array of strings"
        assert unknown == "Error: unknown envelope fields: work_dir"

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
        tool2 = TaskTool(manager=tool._manager, session_id="empty-session")
        result = await tool2.execute(action="list")
        # Should not error, may show "No tasks" or empty list
        assert result is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["status", "wait", "cancel"])
    async def test_task_actions_reject_other_session(self, tool, action):
        """Task IDs cannot be used to inspect or control another session's work."""
        task = await tool._manager.create_task(
            "Other session task",
            "explorer",
            parent_session_id="other-session",
            auto_start=False,
        )

        result = await tool.execute(action=action, task_id=task.id)

        assert result == f"Task not found: {task.id}"
        assert task.state == TaskState.PENDING

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
