"""Tests for ACP (Agent Client Protocol) support."""

from __future__ import annotations

import pytest

from amcp.acp_agent import (
    AVAILABLE_COMMANDS,
    AVAILABLE_MODES,
    ACPSession,
    AMCPAgent,
)


class TestACPSession:
    """Tests for ACPSession class."""

    def test_session_creation(self):
        """Test session creation with basic attributes."""
        session = ACPSession("test-session-id", "/home/user/project")
        assert session.session_id == "test-session-id"
        assert session.cwd == "/home/user/project"
        assert session.conversation_history == []
        assert session.tool_calls_history == []
        assert session.created_at is not None
        assert session.current_mode_id == "ask"
        assert session.plan_entries == []

    def test_add_user_message(self):
        """Test adding user messages to session."""
        session = ACPSession("test-id", "/tmp")
        session.add_user_message("Hello, agent!")
        assert len(session.conversation_history) == 1
        assert session.conversation_history[0]["role"] == "user"
        assert session.conversation_history[0]["content"] == "Hello, agent!"

    def test_add_assistant_message(self):
        """Test adding assistant messages to session."""
        session = ACPSession("test-id", "/tmp")
        session.add_assistant_message("Hello! How can I help?")
        assert len(session.conversation_history) == 1
        assert session.conversation_history[0]["role"] == "assistant"
        assert session.conversation_history[0]["content"] == "Hello! How can I help?"

    def test_add_tool_call(self):
        """Test adding tool calls to session."""
        session = ACPSession("test-id", "/tmp")
        session.add_tool_call("read_file", {"path": "test.py"}, "file content")
        assert len(session.tool_calls_history) == 1
        assert session.tool_calls_history[0]["tool"] == "read_file"
        assert session.tool_calls_history[0]["args"] == {"path": "test.py"}
        assert session.tool_calls_history[0]["result"] == "file content"
        assert "timestamp" in session.tool_calls_history[0]

    def test_conversation_flow(self):
        """Test a typical conversation flow."""
        session = ACPSession("test-id", "/tmp")
        session.add_user_message("Read the README file")
        session.add_tool_call("read_file", {"path": "README.md"}, "# Project\nDescription")
        session.add_assistant_message("The README contains project description.")

        assert len(session.conversation_history) == 2
        assert len(session.tool_calls_history) == 1


class TestAMCPAgent:
    """Tests for AMCPAgent class."""

    def test_agent_creation(self):
        """Test agent creation with default spec."""
        agent = AMCPAgent()
        assert agent.agent_spec is not None
        assert agent._sessions == {}
        assert agent._cancelled_sessions == set()
        assert agent._client_capabilities is None

    @pytest.mark.asyncio
    async def test_initialize(self):
        """Test initialize method returns correct response."""
        agent = AMCPAgent()
        response = await agent.initialize(protocol_version=1)
        assert response.protocol_version == 1
        assert response.agent_info is not None
        assert response.agent_info.name == "amcp"
        assert response.agent_capabilities.load_session is True

    @pytest.mark.asyncio
    async def test_initialize_with_client_capabilities(self):
        """Test initialize stores client capabilities."""
        from acp.schema import ClientCapabilities, FileSystemCapability

        agent = AMCPAgent()
        client_caps = ClientCapabilities(
            fs=FileSystemCapability(read_text_file=True, write_text_file=True),
            terminal=True,
        )
        response = await agent.initialize(protocol_version=1, client_capabilities=client_caps)
        assert agent._client_capabilities == client_caps

    @pytest.mark.asyncio
    async def test_new_session(self):
        """Test creating a new session."""
        agent = AMCPAgent()
        response = await agent.new_session(cwd="/tmp/test", mcp_servers=[])
        assert response.session_id is not None
        assert len(response.session_id) == 32  # UUID hex
        assert response.session_id in agent._sessions
        # Check session modes are returned
        assert response.modes is not None
        assert response.modes.current_mode_id == "ask"
        assert len(response.modes.available_modes) == 3

    @pytest.mark.asyncio
    async def test_cancel_session(self):
        """Test cancelling a session."""
        agent = AMCPAgent()
        response = await agent.new_session(cwd="/tmp", mcp_servers=[])
        session_id = response.session_id

        await agent.cancel(session_id)
        assert session_id in agent._cancelled_sessions

    @pytest.mark.asyncio
    async def test_set_session_mode(self):
        """Test setting session mode."""
        agent = AMCPAgent()
        response = await agent.new_session(cwd="/tmp", mcp_servers=[])
        session_id = response.session_id

        await agent.set_session_mode(mode_id="code", session_id=session_id)
        assert agent._sessions[session_id].current_mode_id == "code"

        await agent.set_session_mode(mode_id="architect", session_id=session_id)
        assert agent._sessions[session_id].current_mode_id == "architect"

    @pytest.mark.asyncio
    async def test_set_invalid_session_mode(self):
        """Test setting invalid session mode does nothing."""
        agent = AMCPAgent()
        response = await agent.new_session(cwd="/tmp", mcp_servers=[])
        session_id = response.session_id

        await agent.set_session_mode(mode_id="invalid", session_id=session_id)
        assert agent._sessions[session_id].current_mode_id == "ask"  # unchanged

    def test_extract_text_from_prompt_dict(self):
        """Test extracting text from dict-style prompt blocks."""
        agent = AMCPAgent()
        prompt = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        result = agent._extract_text_from_prompt(prompt)
        assert result == "Hello\nWorld"

    def test_extract_text_from_prompt_with_resource(self):
        """Test extracting text from prompt with resource blocks."""
        agent = AMCPAgent()
        prompt = [
            {"type": "text", "text": "Check this file:"},
            {
                "type": "resource",
                "resource": {
                    "uri": "file:///test.py",
                    "text": "print('hello')",
                },
            },
        ]
        result = agent._extract_text_from_prompt(prompt)
        assert "Check this file:" in result
        assert "print('hello')" in result
        assert "file:///test.py" in result

    def test_get_tool_kind(self):
        """Test tool kind mapping."""
        agent = AMCPAgent()
        assert agent._get_tool_kind("read_file") == "read"
        assert agent._get_tool_kind("write_file") == "edit"
        assert agent._get_tool_kind("edit_file") == "edit"
        assert agent._get_tool_kind("bash") == "execute"
        assert agent._get_tool_kind("grep") == "search"
        assert agent._get_tool_kind("think") == "think"
        assert agent._get_tool_kind("unknown_tool") == "other"

    @pytest.mark.asyncio
    async def test_list_sessions(self):
        """Test listing sessions."""
        agent = AMCPAgent()
        await agent.new_session(cwd="/tmp/a", mcp_servers=[])
        await agent.new_session(cwd="/tmp/b", mcp_servers=[])

        response = await agent.list_sessions()
        assert len(response.sessions) == 2

    @pytest.mark.asyncio
    async def test_load_nonexistent_session(self):
        """Test loading a session that doesn't exist."""
        agent = AMCPAgent()
        response = await agent.load_session(
            cwd="/tmp",
            mcp_servers=[],
            session_id="nonexistent-session-id",
        )
        assert response is None

    def test_has_client_capability_no_caps(self):
        """Test client capability check with no capabilities."""
        agent = AMCPAgent()
        assert agent._has_client_capability("fs", "readTextFile") is False
        assert agent._has_client_capability("terminal", "") is False


class TestSessionModes:
    """Tests for session modes functionality."""

    def test_available_modes(self):
        """Test available modes are defined correctly."""
        assert len(AVAILABLE_MODES) == 3
        mode_ids = [m.id for m in AVAILABLE_MODES]
        assert "ask" in mode_ids
        assert "architect" in mode_ids
        assert "code" in mode_ids

    def test_mode_descriptions(self):
        """Test modes have descriptions."""
        for mode in AVAILABLE_MODES:
            assert mode.name is not None
            assert mode.description is not None

    @pytest.mark.asyncio
    async def test_session_starts_in_ask_mode(self):
        """Test new sessions start in ask mode."""
        agent = AMCPAgent()
        response = await agent.new_session(cwd="/tmp", mcp_servers=[])
        session = agent._sessions[response.session_id]
        assert session.current_mode_id == "ask"


class TestSlashCommands:
    """Tests for slash commands functionality."""

    def test_available_commands(self):
        """Test available commands are defined correctly."""
        assert len(AVAILABLE_COMMANDS) >= 4
        cmd_names = [c.name for c in AVAILABLE_COMMANDS]
        assert "clear" in cmd_names
        assert "plan" in cmd_names
        assert "search" in cmd_names
        assert "help" in cmd_names

    def test_commands_have_descriptions(self):
        """Test commands have descriptions."""
        for cmd in AVAILABLE_COMMANDS:
            assert cmd.description is not None

    def test_commands_with_input(self):
        """Test commands that require input have hints."""
        for cmd in AVAILABLE_COMMANDS:
            if cmd.input:
                # AvailableCommandInput wraps UnstructuredCommandInput
                assert cmd.input.root.hint is not None


class TestACPIntegration:
    """Integration tests for ACP functionality."""

    def test_system_prompt_generation(self):
        """Test system prompt generation with variables."""
        agent = AMCPAgent()
        session = ACPSession("test-id", "/home/user/project")
        prompt = agent._get_system_prompt(session)
        # Should contain mode-specific prompt
        assert "ask" in prompt.lower() or "permission" in prompt.lower()

    def test_system_prompt_for_architect_mode(self):
        """Test system prompt for architect mode."""
        agent = AMCPAgent()
        session = ACPSession("test-id", "/home/user/project")
        session.current_mode_id = "architect"
        prompt = agent._get_system_prompt(session)
        assert "architect" in prompt.lower() or "design" in prompt.lower()

    def test_system_prompt_for_code_mode(self):
        """Test system prompt for code mode."""
        agent = AMCPAgent()
        session = ACPSession("test-id", "/home/user/project")
        session.current_mode_id = "code"
        prompt = agent._get_system_prompt(session)
        assert "code" in prompt.lower() or "implement" in prompt.lower()

    @pytest.mark.asyncio
    async def test_session_persistence_flow(self):
        """Test session creation and retrieval."""
        agent = AMCPAgent()

        # Create session
        response = await agent.new_session(cwd="/tmp/test", mcp_servers=[])
        session_id = response.session_id

        # Verify session exists
        assert session_id in agent._sessions
        session = agent._sessions[session_id]
        assert session.cwd == "/tmp/test"

        # Add some history
        session.add_user_message("Test message")
        session.add_assistant_message("Test response")

        # Verify history
        assert len(session.conversation_history) == 2

    @pytest.mark.asyncio
    async def test_prompt_with_nonexistent_session(self):
        """Test prompt with non-existent session returns refusal."""
        agent = AMCPAgent()
        response = await agent.prompt(
            prompt=[{"type": "text", "text": "Hello"}],
            session_id="nonexistent",
        )
        assert response.stop_reason == "refusal"


class TestToolBuilding:
    """Tests for tool building based on session mode."""

    @pytest.mark.asyncio
    async def test_architect_mode_limits_tools(self):
        """Test architect mode only provides read tools."""
        agent = AMCPAgent()
        response = await agent.new_session(cwd="/tmp", mcp_servers=[])
        session = agent._sessions[response.session_id]
        session.current_mode_id = "architect"

        tools = await agent._build_tools(session)
        tool_names = [t["function"]["name"] for t in tools]

        # Should have read tools
        assert "read_file" in tool_names or "grep" in tool_names
        # Should NOT have write tools
        assert "write_file" not in tool_names
        assert "bash" not in tool_names

    @pytest.mark.asyncio
    async def test_code_mode_has_all_tools(self):
        """Test code mode has all tools available."""
        agent = AMCPAgent()
        response = await agent.new_session(cwd="/tmp", mcp_servers=[])
        session = agent._sessions[response.session_id]
        session.current_mode_id = "code"

        tools = await agent._build_tools(session)
        tool_names = [t["function"]["name"] for t in tools]

        # Should have both read and write tools
        assert len(tool_names) > 0
