from types import SimpleNamespace

from amcp.memory import get_memory_manager, reset_memory_manager
from amcp.memory_dream import MemoryDreamer


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.content)


def test_memory_dreamer_consolidates_recent_events(tmp_path):
    reset_memory_manager()
    manager = get_memory_manager(tmp_path)
    manager.append_history("User is planning Telegram memory improvements", session_id="s1", scope="project")
    manager.append_history("Need proactive heartbeat support", session_id="s1", scope="project")
    client = _FakeClient("# Project Memory\n- User is planning Telegram memory improvements.")
    dreamer = MemoryDreamer(
        tmp_path,
        min_interval_seconds=0,
        min_new_events=2,
        client=client,
        model="test-model",
    )

    result = dreamer.run_once()

    assert result.ran is True
    assert result.updated is True
    assert "Telegram memory improvements" in manager.read_long_term(scope="project")
    assert client.calls
    reset_memory_manager()


def test_memory_dreamer_skips_until_enough_events(tmp_path):
    reset_memory_manager()
    manager = get_memory_manager(tmp_path)
    manager.append_history("Only one event", session_id="s1", scope="project")
    dreamer = MemoryDreamer(
        tmp_path,
        min_interval_seconds=0,
        min_new_events=2,
        client=_FakeClient("# Memory\n- no-op"),
        model="test-model",
    )

    result = dreamer.run_once()

    assert result.ran is False
    assert result.reason == "not_enough_new_events"
    reset_memory_manager()
