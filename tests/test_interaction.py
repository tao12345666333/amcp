"""Tests for shared interaction routing."""

from amcp.commands import reset_command_manager
from amcp.interaction import route_interaction


def test_plain_message_routes_to_prompt():
    result = route_interaction("hello")

    assert result.action == "prompt"
    assert result.content == "hello"


def test_new_command_routes_to_new_session():
    reset_command_manager()

    result = route_interaction("/new")

    assert result.action == "new_session"


def test_session_commands_route_to_session_actions():
    reset_command_manager()

    assert route_interaction("/session list").action == "session_list"
    assert route_interaction("/session new").action == "new_session"

    switch = route_interaction("/session switch session-123")
    assert switch.action == "session_switch"
    assert switch.session_id == "session-123"


def test_unknown_command_returns_message():
    reset_command_manager()

    result = route_interaction("/does-not-exist")

    assert result.action == "message"
    assert result.message_type == "error"
    assert "Unknown command" in result.content
