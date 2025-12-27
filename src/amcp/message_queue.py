"""
Session-level Message Queue for AMCP.

This module provides message queuing capabilities for agent sessions,
inspired by Crush's sessionAgent message queue implementation.

Key Features:
- Session-specific message queues (messages are isolated per session)
- Priority support for urgent messages
- Automatic queuing when session is busy
- Queue management (clear, peek, list)
- Async/await compatible

The queue ensures that:
1. A session can only process one request at a time
2. Incoming messages are queued while the session is busy
3. Queued messages are processed in order when the session becomes free
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MessagePriority(Enum):
    """Priority levels for queued messages."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


@dataclass
class QueuedMessage:
    """A message waiting in the queue.

    Attributes:
        id: Unique message identifier
        session_id: Session this message belongs to
        prompt: User's input prompt
        attachments: Optional file attachments
        priority: Message priority (default NORMAL)
        created_at: When the message was queued
        metadata: Additional message metadata
    """

    id: str
    session_id: str
    prompt: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    priority: MessagePriority = MessagePriority.NORMAL
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        session_id: str,
        prompt: str,
        attachments: list[dict[str, Any]] | None = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        **metadata: Any,
    ) -> QueuedMessage:
        """Create a new queued message.

        Args:
            session_id: Target session ID
            prompt: User's prompt text
            attachments: Optional attachments
            priority: Message priority
            **metadata: Additional metadata

        Returns:
            New QueuedMessage instance
        """
        return cls(
            id=str(uuid.uuid4()),
            session_id=session_id,
            prompt=prompt,
            attachments=attachments or [],
            priority=priority,
            metadata=metadata,
        )


class SessionQueue:
    """Message queue for a single session.

    Manages a FIFO queue of messages for one session,
    with support for priorities.
    """

    def __init__(self, session_id: str):
        """Initialize session queue.

        Args:
            session_id: Session identifier
        """
        self.session_id = session_id
        self._queue: deque[QueuedMessage] = deque()
        self._lock = asyncio.Lock()

    def __len__(self) -> int:
        """Get the number of messages in the queue."""
        return len(self._queue)

    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return len(self._queue) == 0

    async def enqueue(self, message: QueuedMessage) -> None:
        """Add a message to the queue.

        Messages are ordered by priority, then by creation time.

        Args:
            message: Message to add
        """
        async with self._lock:
            # Find insertion point based on priority
            insert_idx = len(self._queue)
            for i, existing in enumerate(self._queue):
                if message.priority.value > existing.priority.value:
                    insert_idx = i
                    break

            self._queue.insert(insert_idx, message)

    async def dequeue(self) -> QueuedMessage | None:
        """Remove and return the next message from the queue.

        Returns:
            Next message or None if queue is empty
        """
        async with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    async def peek(self) -> QueuedMessage | None:
        """Look at the next message without removing it.

        Returns:
            Next message or None if queue is empty
        """
        async with self._lock:
            if self._queue:
                return self._queue[0]
            return None

    async def clear(self) -> int:
        """Clear all messages from the queue.

        Returns:
            Number of messages cleared
        """
        async with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return count

    def list_messages(self) -> list[QueuedMessage]:
        """Get a copy of all queued messages.

        Returns:
            List of queued messages
        """
        return list(self._queue)

    def list_prompts(self) -> list[str]:
        """Get list of queued prompts for display.

        Returns:
            List of prompt strings
        """
        return [msg.prompt for msg in self._queue]


class MessageQueueManager:
    """Manages message queues for multiple sessions.

    Provides centralized management of session queues,
    busy state tracking, and message routing.

    Example usage:
        manager = MessageQueueManager()

        # Check if session is busy
        if manager.is_busy("session-123"):
            # Enqueue the message
            await manager.enqueue("session-123", "Hello!")
        else:
            # Process immediately
            await manager.acquire("session-123")
            try:
                result = await process_message(prompt)
            finally:
                manager.release("session-123")

            # Process any queued messages
            while True:
                next_msg = await manager.dequeue("session-123")
                if not next_msg:
                    break
                # Process next_msg...
    """

    def __init__(self):
        """Initialize the message queue manager."""
        self._session_queues: dict[str, SessionQueue] = {}
        self._busy_sessions: set[str] = set()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def _get_or_create_queue(self, session_id: str) -> SessionQueue:
        """Get or create a queue for a session.

        Args:
            session_id: Session identifier

        Returns:
            Session queue
        """
        if session_id not in self._session_queues:
            self._session_queues[session_id] = SessionQueue(session_id)
        return self._session_queues[session_id]

    def _get_or_create_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a lock for a session.

        Args:
            session_id: Session identifier

        Returns:
            Session lock
        """
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    def is_busy(self, session_id: str) -> bool:
        """Check if a session is currently busy.

        Args:
            session_id: Session identifier

        Returns:
            True if session is processing a request
        """
        return session_id in self._busy_sessions

    def any_busy(self) -> bool:
        """Check if any session is busy.

        Returns:
            True if any session is processing
        """
        return len(self._busy_sessions) > 0

    def get_busy_sessions(self) -> list[str]:
        """Get list of busy session IDs.

        Returns:
            List of busy session IDs
        """
        return list(self._busy_sessions)

    async def acquire(self, session_id: str) -> bool:
        """Acquire exclusive access to a session.

        Use this before processing a request for a session.

        Args:
            session_id: Session identifier

        Returns:
            True if acquired, False if session was already busy
        """
        async with self._global_lock:
            if session_id in self._busy_sessions:
                return False
            self._busy_sessions.add(session_id)
            return True

    def release(self, session_id: str) -> None:
        """Release a session after processing.

        Use this after finishing processing a request.

        Args:
            session_id: Session identifier
        """
        self._busy_sessions.discard(session_id)

    async def enqueue(
        self,
        session_id: str,
        prompt: str,
        attachments: list[dict[str, Any]] | None = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        **metadata: Any,
    ) -> QueuedMessage:
        """Add a message to a session's queue.

        Use this when a session is busy and cannot process immediately.

        Args:
            session_id: Target session ID
            prompt: User's prompt text
            attachments: Optional attachments
            priority: Message priority
            **metadata: Additional metadata

        Returns:
            The queued message
        """
        queue = self._get_or_create_queue(session_id)
        message = QueuedMessage.create(
            session_id=session_id,
            prompt=prompt,
            attachments=attachments,
            priority=priority,
            **metadata,
        )
        await queue.enqueue(message)
        return message

    async def enqueue_if_busy(
        self,
        session_id: str,
        prompt: str,
        attachments: list[dict[str, Any]] | None = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        **metadata: Any,
    ) -> tuple[bool, QueuedMessage | None]:
        """Automatically enqueue a message if session is busy.

        This is a convenience method that:
        1. Checks if the session is busy
        2. If busy, queues the message and returns (True, message)
        3. If not busy, returns (False, None)

        Args:
            session_id: Target session ID
            prompt: User's prompt text
            attachments: Optional attachments
            priority: Message priority
            **metadata: Additional metadata

        Returns:
            Tuple of (was_queued, queued_message)
        """
        if self.is_busy(session_id):
            message = await self.enqueue(session_id, prompt, attachments, priority, **metadata)
            return (True, message)
        return (False, None)

    async def dequeue(self, session_id: str) -> QueuedMessage | None:
        """Get the next queued message for a session.

        Args:
            session_id: Session identifier

        Returns:
            Next message or None if queue is empty
        """
        queue = self._get_or_create_queue(session_id)
        return await queue.dequeue()

    async def peek(self, session_id: str) -> QueuedMessage | None:
        """Look at the next message without removing it.

        Args:
            session_id: Session identifier

        Returns:
            Next message or None if queue is empty
        """
        queue = self._get_or_create_queue(session_id)
        return await queue.peek()

    def queued_count(self, session_id: str) -> int:
        """Get the number of queued messages for a session.

        Args:
            session_id: Session identifier

        Returns:
            Number of queued messages
        """
        if session_id not in self._session_queues:
            return 0
        return len(self._session_queues[session_id])

    def queued_prompts(self, session_id: str) -> list[str]:
        """Get list of queued prompts for a session.

        Useful for displaying queue status to users.

        Args:
            session_id: Session identifier

        Returns:
            List of prompt strings
        """
        if session_id not in self._session_queues:
            return []
        return self._session_queues[session_id].list_prompts()

    async def clear_queue(self, session_id: str) -> int:
        """Clear all queued messages for a session.

        Args:
            session_id: Session identifier

        Returns:
            Number of messages cleared
        """
        if session_id not in self._session_queues:
            return 0
        return await self._session_queues[session_id].clear()

    def get_queue_status(self, session_id: str) -> dict[str, Any]:
        """Get detailed queue status for a session.

        Args:
            session_id: Session identifier

        Returns:
            Status dictionary
        """
        return {
            "session_id": session_id,
            "is_busy": self.is_busy(session_id),
            "queued_count": self.queued_count(session_id),
            "queued_prompts": self.queued_prompts(session_id),
        }

    def get_all_status(self) -> dict[str, Any]:
        """Get status for all sessions.

        Returns:
            Status dictionary for all sessions
        """
        return {
            "busy_sessions": self.get_busy_sessions(),
            "total_queued": sum(len(q) for q in self._session_queues.values()),
            "sessions": {
                sid: self.get_queue_status(sid) for sid in set(self._session_queues.keys()) | self._busy_sessions
            },
        }


# Global message queue manager singleton
_queue_manager: MessageQueueManager | None = None


def get_message_queue_manager() -> MessageQueueManager:
    """Get the global message queue manager.

    Returns:
        Global MessageQueueManager instance
    """
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = MessageQueueManager()
    return _queue_manager


async def run_with_queue(
    session_id: str,
    prompt: str,
    processor_fn,
    attachments: list[dict[str, Any]] | None = None,
    priority: MessagePriority = MessagePriority.NORMAL,
) -> Any | None:
    """Run a prompt through the queue system.

    This is a high-level helper that:
    1. Queues the message if session is busy
    2. Otherwise processes immediately
    3. After processing, checks for and processes queued messages

    Args:
        session_id: Session identifier
        prompt: User's prompt
        processor_fn: Async function(prompt, attachments) to process the message
        attachments: Optional attachments
        priority: Message priority

    Returns:
        Result from processor_fn, or None if queued
    """
    manager = get_message_queue_manager()

    # Check if we should queue
    was_queued, _ = await manager.enqueue_if_busy(session_id, prompt, attachments, priority)
    if was_queued:
        return None

    # Acquire the session
    acquired = await manager.acquire(session_id)
    if not acquired:
        # Race condition - queue it
        await manager.enqueue(session_id, prompt, attachments, priority)
        return None

    try:
        # Process the message
        result = await processor_fn(prompt, attachments or [])

        # Process any queued messages
        while True:
            next_msg = await manager.dequeue(session_id)
            if not next_msg:
                break
            # Process queued message
            await processor_fn(next_msg.prompt, next_msg.attachments)

        return result

    finally:
        manager.release(session_id)
