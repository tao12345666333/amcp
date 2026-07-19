from unittest.mock import patch

from amcp.session_search import TranscriptStore
from amcp.tools import SessionSearchTool


def test_transcript_store_appends_and_searches_turn(tmp_path):
    store = TranscriptStore(tmp_path / "transcripts.db")
    store.append_turn(
        session_id="s1",
        user="We need to migrate Telegram memory",
        assistant="I will plan the migration.",
        source="telegram",
        chat_id="123",
    )

    results = store.search("Telegram memory", max_results=5)

    assert results
    assert results[0].session_id == "s1"
    assert results[0].source == "telegram"
    assert results[0].chat_id == "123"
    assert results[0].role in {"user", "assistant"}


def test_transcript_store_filters_by_session(tmp_path):
    store = TranscriptStore(tmp_path / "transcripts.db")
    store.append_message(session_id="s1", role="user", content="alpha topic")
    store.append_message(session_id="s2", role="user", content="alpha topic")

    results = store.search("alpha", session_id="s2")

    assert [result.session_id for result in results] == ["s2"]


def test_session_search_tool_formats_results(tmp_path):
    store = TranscriptStore(tmp_path / "transcripts.db")
    store.append_message(
        session_id="s1",
        role="assistant",
        content="Finished the autoDream memory consolidation plan",
        source="agent",
    )

    tool = SessionSearchTool()

    with patch("amcp.session_search.get_transcript_store", return_value=store):
        result = tool.execute(query="autoDream")

    assert result.success is True
    assert "Found 1 transcript results" in result.content
    assert "autoDream" in result.content
