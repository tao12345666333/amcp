"""Tests for the event_bus module."""

import asyncio

import pytest

from amcp.event_bus import (
    Event,
    EventBus,
    EventHandler,
    EventPriority,
    EventType,
    get_event_bus,
    reset_event_bus,
)


@pytest.fixture
def event_bus():
    """Create a fresh event bus for each test."""
    return EventBus()


@pytest.fixture(autouse=True)
def reset_global_bus():
    """Reset global event bus before and after each test."""
    reset_event_bus()
    yield
    reset_event_bus()


class TestEventType:
    """Tests for EventType enum."""

    def test_agent_events(self):
        """Test agent lifecycle events."""
        assert EventType.AGENT_STARTED.value == "agent.started"
        assert EventType.AGENT_COMPLETED.value == "agent.completed"
        assert EventType.AGENT_ERROR.value == "agent.error"

    def test_tool_events(self):
        """Test tool events."""
        assert EventType.TOOL_STARTED.value == "tool.started"
        assert EventType.TOOL_COMPLETED.value == "tool.completed"
        assert EventType.TOOL_ERROR.value == "tool.error"

    def test_task_events(self):
        """Test task events."""
        assert EventType.TASK_CREATED.value == "task.created"
        assert EventType.TASK_STARTED.value == "task.started"
        assert EventType.TASK_COMPLETED.value == "task.completed"


class TestEvent:
    """Tests for Event dataclass."""

    def test_create_event(self):
        """Test creating an event."""
        event = Event(
            type=EventType.TOOL_COMPLETED,
            data={"tool_name": "read_file"},
            source="test",
            session_id="session-123",
        )
        assert event.type == EventType.TOOL_COMPLETED
        assert event.data["tool_name"] == "read_file"
        assert event.source == "test"
        assert event.session_id == "session-123"
        assert event.id is not None
        assert event.timestamp is not None

    def test_event_defaults(self):
        """Test event default values."""
        event = Event(type=EventType.CUSTOM)
        assert event.data == {}
        assert event.source == ""
        assert event.session_id is None
        assert event.metadata == {}


class TestEventHandler:
    """Tests for EventHandler dataclass."""

    def test_matches_any_event(self):
        """Test handler matching any event type."""
        handler = EventHandler(
            id="test",
            callback=lambda e: None,
            event_types=None,  # Match all
        )
        event = Event(type=EventType.TOOL_COMPLETED)
        assert handler.matches(event)

    def test_matches_specific_type(self):
        """Test handler matching specific event type."""
        handler = EventHandler(
            id="test",
            callback=lambda e: None,
            event_types={EventType.TOOL_COMPLETED},
        )
        assert handler.matches(Event(type=EventType.TOOL_COMPLETED))
        assert not handler.matches(Event(type=EventType.TOOL_STARTED))

    def test_matches_session_filter(self):
        """Test handler with session filter."""
        handler = EventHandler(
            id="test",
            callback=lambda e: None,
            event_types=None,
            session_filter="session-123",
        )
        assert handler.matches(Event(type=EventType.CUSTOM, session_id="session-123"))
        assert not handler.matches(Event(type=EventType.CUSTOM, session_id="other"))
        assert not handler.matches(Event(type=EventType.CUSTOM, session_id=None))


class TestEventBus:
    """Tests for EventBus class."""

    def test_subscribe(self, event_bus):
        """Test subscribing to events."""
        handler_id = event_bus.subscribe(
            event_types=EventType.TOOL_COMPLETED,
            callback=lambda e: None,
        )
        assert handler_id is not None
        assert event_bus.handler_count() == 1

    def test_unsubscribe(self, event_bus):
        """Test unsubscribing from events."""
        handler_id = event_bus.subscribe(
            event_types=EventType.TOOL_COMPLETED,
            callback=lambda e: None,
        )
        assert event_bus.unsubscribe(handler_id)
        assert event_bus.handler_count() == 0

    def test_unsubscribe_nonexistent(self, event_bus):
        """Test unsubscribing non-existent handler."""
        assert not event_bus.unsubscribe("nonexistent")

    @pytest.mark.asyncio
    async def test_emit_calls_handler(self, event_bus):
        """Test that emit calls matching handlers."""
        results = []

        def handler(event):
            results.append(event.data["value"])

        event_bus.subscribe(EventType.CUSTOM, handler)
        await event_bus.emit(Event(type=EventType.CUSTOM, data={"value": 42}))

        assert results == [42]

    @pytest.mark.asyncio
    async def test_emit_async_handler(self, event_bus):
        """Test emitting to async handlers."""
        results = []

        async def handler(event):
            await asyncio.sleep(0.01)
            results.append(event.data["value"])

        event_bus.subscribe(EventType.CUSTOM, handler)
        await event_bus.emit(Event(type=EventType.CUSTOM, data={"value": 42}))

        assert results == [42]

    @pytest.mark.asyncio
    async def test_emit_multiple_handlers(self, event_bus):
        """Test emitting to multiple handlers."""
        results = []

        def handler1(event):
            results.append(1)

        def handler2(event):
            results.append(2)

        event_bus.subscribe(EventType.CUSTOM, handler1)
        event_bus.subscribe(EventType.CUSTOM, handler2)
        await event_bus.emit(Event(type=EventType.CUSTOM))

        assert 1 in results
        assert 2 in results

    @pytest.mark.asyncio
    async def test_handler_priority(self, event_bus):
        """Test handler priority ordering."""
        results = []

        event_bus.subscribe(
            EventType.CUSTOM,
            lambda e: results.append("low"),
            priority=EventPriority.LOW,
        )
        event_bus.subscribe(
            EventType.CUSTOM,
            lambda e: results.append("high"),
            priority=EventPriority.HIGH,
        )
        event_bus.subscribe(
            EventType.CUSTOM,
            lambda e: results.append("normal"),
            priority=EventPriority.NORMAL,
        )

        await event_bus.emit(Event(type=EventType.CUSTOM))

        # High priority first, then normal, then low
        assert results == ["high", "normal", "low"]

    @pytest.mark.asyncio
    async def test_once_handler(self, event_bus):
        """Test one-time handlers."""
        results = []

        event_bus.subscribe(
            EventType.CUSTOM,
            lambda e: results.append(1),
            once=True,
        )

        await event_bus.emit(Event(type=EventType.CUSTOM))
        await event_bus.emit(Event(type=EventType.CUSTOM))

        # Should only be called once
        assert results == [1]

    def test_emit_sync(self, event_bus):
        """Test synchronous emit."""
        results = []

        event_bus.subscribe(EventType.CUSTOM, lambda e: results.append(1))
        event_bus.emit_sync(Event(type=EventType.CUSTOM))

        assert results == [1]

    def test_clear(self, event_bus):
        """Test clearing all handlers."""
        event_bus.subscribe(EventType.CUSTOM, lambda e: None)
        event_bus.subscribe(EventType.TOOL_STARTED, lambda e: None)

        event_bus.clear()
        assert event_bus.handler_count() == 0

    def test_clear_session(self, event_bus):
        """Test clearing handlers for a session."""
        event_bus.subscribe(EventType.CUSTOM, lambda e: None, session_filter="session-1")
        event_bus.subscribe(EventType.CUSTOM, lambda e: None, session_filter="session-2")
        event_bus.subscribe(EventType.CUSTOM, lambda e: None)  # Global

        removed = event_bus.clear_session("session-1")
        assert removed == 1
        assert event_bus.handler_count() == 2

    @pytest.mark.asyncio
    async def test_get_history(self, event_bus):
        """Test event history."""
        await event_bus.emit(Event(type=EventType.CUSTOM, data={"n": 1}))
        await event_bus.emit(Event(type=EventType.TOOL_STARTED, data={"n": 2}))
        await event_bus.emit(Event(type=EventType.CUSTOM, data={"n": 3}))

        # All history
        history = event_bus.get_history()
        assert len(history) == 3
        assert history[0].data["n"] == 3  # Newest first

        # Filter by type
        custom_history = event_bus.get_history(event_type=EventType.CUSTOM)
        assert len(custom_history) == 2

        # Limit
        limited = event_bus.get_history(limit=1)
        assert len(limited) == 1

    @pytest.mark.asyncio
    async def test_session_filtered_history(self, event_bus):
        """Test history filtering by session."""
        await event_bus.emit(Event(type=EventType.CUSTOM, session_id="s1"))
        await event_bus.emit(Event(type=EventType.CUSTOM, session_id="s2"))
        await event_bus.emit(Event(type=EventType.CUSTOM, session_id="s1"))

        history = event_bus.get_history(session_id="s1")
        assert len(history) == 2

    def test_handler_count(self, event_bus):
        """Test counting handlers."""
        event_bus.subscribe(EventType.CUSTOM, lambda e: None)
        event_bus.subscribe(EventType.TOOL_STARTED, lambda e: None)
        event_bus.subscribe(None, lambda e: None)  # All events

        assert event_bus.handler_count() == 3
        assert event_bus.handler_count(EventType.CUSTOM) == 2  # Specific + all
        assert event_bus.handler_count(EventType.TOOL_STARTED) == 2

    def test_get_stats(self, event_bus):
        """Test getting statistics."""
        event_bus.subscribe(EventType.CUSTOM, lambda e: None, priority=EventPriority.HIGH)
        event_bus.subscribe(EventType.CUSTOM, lambda e: None, priority=EventPriority.NORMAL)

        stats = event_bus.get_stats()
        assert stats["total_handlers"] == 2
        assert stats["handlers_by_priority"]["HIGH"] == 1
        assert stats["handlers_by_priority"]["NORMAL"] == 1

    def test_decorator(self, event_bus):
        """Test decorator for subscribing."""
        results = []

        @event_bus.on(EventType.CUSTOM)
        def handler(event):
            results.append(event.data["value"])

        event_bus.emit_sync(Event(type=EventType.CUSTOM, data={"value": 42}))
        assert results == [42]


class TestGlobalEventBus:
    """Tests for global event bus singleton."""

    def test_singleton(self):
        """Test that get_event_bus returns a singleton."""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_reset(self):
        """Test resetting global event bus."""
        bus1 = get_event_bus()
        bus1.subscribe(EventType.CUSTOM, lambda e: None)

        reset_event_bus()
        bus2 = get_event_bus()

        assert bus1 is not bus2
        assert bus2.handler_count() == 0
