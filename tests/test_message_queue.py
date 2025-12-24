"""Tests for the message_queue module."""

import asyncio

import pytest

from amcp.message_queue import (
    MessagePriority,
    MessageQueueManager,
    QueuedMessage,
    SessionQueue,
    get_message_queue_manager,
    run_with_queue,
)


class TestMessagePriority:
    """Tests for MessagePriority enum."""

    def test_priority_values(self):
        """Test that priority values are ordered correctly."""
        assert MessagePriority.LOW.value < MessagePriority.NORMAL.value
        assert MessagePriority.NORMAL.value < MessagePriority.HIGH.value
        assert MessagePriority.HIGH.value < MessagePriority.URGENT.value

    def test_priority_comparison(self):
        """Test priority comparison."""
        assert MessagePriority.URGENT.value > MessagePriority.LOW.value
        assert MessagePriority.NORMAL.value == 1


class TestQueuedMessage:
    """Tests for QueuedMessage dataclass."""

    def test_create_with_defaults(self):
        """Test creating a message with default values."""
        msg = QueuedMessage.create(
            session_id="test-session",
            prompt="Hello, world!",
        )
        assert msg.session_id == "test-session"
        assert msg.prompt == "Hello, world!"
        assert msg.priority == MessagePriority.NORMAL
        assert msg.attachments == []
        assert msg.metadata == {}
        assert msg.id is not None
        assert msg.created_at is not None

    def test_create_with_priority(self):
        """Test creating a message with custom priority."""
        msg = QueuedMessage.create(
            session_id="test-session",
            prompt="Urgent!",
            priority=MessagePriority.URGENT,
        )
        assert msg.priority == MessagePriority.URGENT

    def test_create_with_attachments(self):
        """Test creating a message with attachments."""
        attachments = [{"file": "test.txt", "content": "Hello"}]
        msg = QueuedMessage.create(
            session_id="test-session",
            prompt="With attachment",
            attachments=attachments,
        )
        assert msg.attachments == attachments

    def test_create_with_metadata(self):
        """Test creating a message with metadata."""
        msg = QueuedMessage.create(
            session_id="test-session",
            prompt="Test",
            work_dir="/home/user",
            stream=True,
        )
        assert msg.metadata["work_dir"] == "/home/user"
        assert msg.metadata["stream"] is True

    def test_unique_ids(self):
        """Test that each message gets a unique ID."""
        msg1 = QueuedMessage.create("session", "Prompt 1")
        msg2 = QueuedMessage.create("session", "Prompt 2")
        assert msg1.id != msg2.id


class TestSessionQueue:
    """Tests for SessionQueue class."""

    @pytest.fixture
    def queue(self):
        """Create a fresh queue for each test."""
        return SessionQueue("test-session")

    @pytest.mark.asyncio
    async def test_enqueue_dequeue(self, queue):
        """Test basic enqueue and dequeue."""
        msg = QueuedMessage.create("test-session", "Hello")
        await queue.enqueue(msg)
        assert len(queue) == 1

        dequeued = await queue.dequeue()
        assert dequeued is not None
        assert dequeued.prompt == "Hello"
        assert len(queue) == 0

    @pytest.mark.asyncio
    async def test_is_empty(self, queue):
        """Test is_empty method."""
        assert queue.is_empty()
        await queue.enqueue(QueuedMessage.create("test-session", "Hello"))
        assert not queue.is_empty()

    @pytest.mark.asyncio
    async def test_priority_ordering(self, queue):
        """Test that messages are ordered by priority."""
        await queue.enqueue(QueuedMessage.create("s", "Normal", priority=MessagePriority.NORMAL))
        await queue.enqueue(QueuedMessage.create("s", "Low", priority=MessagePriority.LOW))
        await queue.enqueue(QueuedMessage.create("s", "Urgent", priority=MessagePriority.URGENT))
        await queue.enqueue(QueuedMessage.create("s", "High", priority=MessagePriority.HIGH))

        # Should dequeue in priority order: URGENT, HIGH, NORMAL, LOW
        prompts = []
        while not queue.is_empty():
            msg = await queue.dequeue()
            prompts.append(msg.prompt)

        assert prompts == ["Urgent", "High", "Normal", "Low"]

    @pytest.mark.asyncio
    async def test_peek(self, queue):
        """Test peek without removing."""
        msg = QueuedMessage.create("test-session", "Hello")
        await queue.enqueue(msg)

        peeked = await queue.peek()
        assert peeked is not None
        assert peeked.prompt == "Hello"
        assert len(queue) == 1  # Still in queue

    @pytest.mark.asyncio
    async def test_dequeue_empty(self, queue):
        """Test dequeue from empty queue returns None."""
        result = await queue.dequeue()
        assert result is None

    @pytest.mark.asyncio
    async def test_clear(self, queue):
        """Test clearing the queue."""
        await queue.enqueue(QueuedMessage.create("s", "1"))
        await queue.enqueue(QueuedMessage.create("s", "2"))
        await queue.enqueue(QueuedMessage.create("s", "3"))

        count = await queue.clear()
        assert count == 3
        assert queue.is_empty()

    def test_list_messages(self, queue):
        """Test listing messages without async."""
        # We need to run async operations
        asyncio.run(queue.enqueue(QueuedMessage.create("s", "Hello")))
        messages = queue.list_messages()
        assert len(messages) == 1
        assert messages[0].prompt == "Hello"

    def test_list_prompts(self, queue):
        """Test listing prompts."""
        asyncio.run(queue.enqueue(QueuedMessage.create("s", "Hello")))
        asyncio.run(queue.enqueue(QueuedMessage.create("s", "World")))
        prompts = queue.list_prompts()
        assert prompts == ["Hello", "World"]


class TestMessageQueueManager:
    """Tests for MessageQueueManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh manager for each test."""
        return MessageQueueManager()

    @pytest.mark.asyncio
    async def test_acquire_release(self, manager):
        """Test session acquire and release."""
        assert not manager.is_busy("session-1")

        acquired = await manager.acquire("session-1")
        assert acquired
        assert manager.is_busy("session-1")

        manager.release("session-1")
        assert not manager.is_busy("session-1")

    @pytest.mark.asyncio
    async def test_acquire_fails_when_busy(self, manager):
        """Test that acquire fails when session is already busy."""
        await manager.acquire("session-1")
        assert manager.is_busy("session-1")

        # Try to acquire again
        acquired_again = await manager.acquire("session-1")
        assert not acquired_again

    @pytest.mark.asyncio
    async def test_multiple_sessions(self, manager):
        """Test managing multiple sessions."""
        await manager.acquire("session-1")
        await manager.acquire("session-2")

        assert manager.is_busy("session-1")
        assert manager.is_busy("session-2")
        assert not manager.is_busy("session-3")

        busy_sessions = manager.get_busy_sessions()
        assert "session-1" in busy_sessions
        assert "session-2" in busy_sessions

    @pytest.mark.asyncio
    async def test_any_busy(self, manager):
        """Test any_busy method."""
        assert not manager.any_busy()

        await manager.acquire("session-1")
        assert manager.any_busy()

        manager.release("session-1")
        assert not manager.any_busy()

    @pytest.mark.asyncio
    async def test_enqueue(self, manager):
        """Test enqueueing messages."""
        msg = await manager.enqueue("session-1", "Hello")
        assert msg.prompt == "Hello"
        assert manager.queued_count("session-1") == 1

    @pytest.mark.asyncio
    async def test_enqueue_if_busy(self, manager):
        """Test enqueue_if_busy method."""
        # Not busy - should not queue
        was_queued, msg = await manager.enqueue_if_busy("session-1", "Hello")
        assert not was_queued
        assert msg is None

        # Now make it busy
        await manager.acquire("session-1")

        # Should queue now
        was_queued, msg = await manager.enqueue_if_busy("session-1", "World")
        assert was_queued
        assert msg is not None
        assert msg.prompt == "World"

    @pytest.mark.asyncio
    async def test_dequeue(self, manager):
        """Test dequeueing messages."""
        await manager.enqueue("session-1", "Hello")
        await manager.enqueue("session-1", "World")

        msg = await manager.dequeue("session-1")
        assert msg.prompt == "Hello"

        msg = await manager.dequeue("session-1")
        assert msg.prompt == "World"

        msg = await manager.dequeue("session-1")
        assert msg is None

    @pytest.mark.asyncio
    async def test_peek(self, manager):
        """Test peeking messages."""
        await manager.enqueue("session-1", "Hello")

        msg = await manager.peek("session-1")
        assert msg.prompt == "Hello"
        assert manager.queued_count("session-1") == 1

    @pytest.mark.asyncio
    async def test_clear_queue(self, manager):
        """Test clearing a session's queue."""
        await manager.enqueue("session-1", "1")
        await manager.enqueue("session-1", "2")
        await manager.enqueue("session-1", "3")

        count = await manager.clear_queue("session-1")
        assert count == 3
        assert manager.queued_count("session-1") == 0

    def test_queued_count_empty(self, manager):
        """Test queued_count for non-existent session."""
        assert manager.queued_count("nonexistent") == 0

    def test_queued_prompts_empty(self, manager):
        """Test queued_prompts for non-existent session."""
        assert manager.queued_prompts("nonexistent") == []

    @pytest.mark.asyncio
    async def test_queued_prompts(self, manager):
        """Test queued_prompts."""
        await manager.enqueue("session-1", "Hello")
        await manager.enqueue("session-1", "World")

        prompts = manager.queued_prompts("session-1")
        assert prompts == ["Hello", "World"]

    @pytest.mark.asyncio
    async def test_get_queue_status(self, manager):
        """Test get_queue_status method."""
        await manager.enqueue("session-1", "Hello")
        await manager.acquire("session-1")

        status = manager.get_queue_status("session-1")
        assert status["session_id"] == "session-1"
        assert status["is_busy"] is True
        assert status["queued_count"] == 1
        assert "Hello" in status["queued_prompts"]

    @pytest.mark.asyncio
    async def test_get_all_status(self, manager):
        """Test get_all_status method."""
        await manager.acquire("session-1")
        await manager.enqueue("session-2", "Hello")

        status = manager.get_all_status()
        assert "session-1" in status["busy_sessions"]
        assert status["total_queued"] == 1
        assert "sessions" in status


class TestGlobalQueueManager:
    """Tests for global queue manager singleton."""

    def test_singleton(self):
        """Test that get_message_queue_manager returns a singleton."""
        manager1 = get_message_queue_manager()
        manager2 = get_message_queue_manager()
        assert manager1 is manager2


class TestRunWithQueue:
    """Tests for run_with_queue helper function."""

    @pytest.mark.asyncio
    async def test_processes_immediately_when_not_busy(self):
        """Test that messages are processed immediately when not busy."""
        processed = []

        async def processor(prompt, attachments):
            processed.append(prompt)
            return f"Result: {prompt}"

        # Use a unique session for this test
        result = await run_with_queue("run-test-1", "Hello", processor)
        assert result == "Result: Hello"
        assert "Hello" in processed

    @pytest.mark.asyncio
    async def test_returns_none_when_queued(self):
        """Test that queued messages return None."""
        manager = get_message_queue_manager()

        # Acquire the session first
        await manager.acquire("run-test-2")

        async def processor(prompt, attachments):
            return f"Result: {prompt}"

        try:
            result = await run_with_queue("run-test-2", "Hello", processor)
            assert result is None  # Queued, not processed
        finally:
            manager.release("run-test-2")
            # Clean up
            await manager.clear_queue("run-test-2")
