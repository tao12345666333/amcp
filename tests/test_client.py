"""Tests for AMCP Client SDK."""

from __future__ import annotations

import pytest

from amcp.client import (
    AMCPClient,
    BaseClient,
    ClientMode,
    ClientSession,
    HTTPClient,
)
from amcp.client.base import ResponseChunk
from amcp.client.embedded import EmbeddedClient
from amcp.client.exceptions import (
    AMCPClientError,
    ConnectionError,
    PromptError,
    SessionError,
    SessionNotFoundError,
    TimeoutError,
)


# ============================================================================
# Test Exceptions
# ============================================================================


class TestExceptions:
    """Test exception classes."""

    def test_amcp_client_error(self):
        """Test base exception."""
        err = AMCPClientError("test error", code="TEST_CODE", details={"key": "value"})
        assert str(err) == "test error"
        assert err.message == "test error"
        assert err.code == "TEST_CODE"
        assert err.details == {"key": "value"}

    def test_connection_error(self):
        """Test connection error."""
        err = ConnectionError("failed to connect")
        assert "failed to connect" in str(err)
        assert err.code == "CONNECTION_ERROR"

    def test_session_not_found_error(self):
        """Test session not found error."""
        err = SessionNotFoundError("session-123")
        assert "session-123" in str(err)
        assert err.session_id == "session-123"
        assert err.code == "SESSION_NOT_FOUND"

    def test_timeout_error(self):
        """Test timeout error."""
        err = TimeoutError("timeout", timeout=30.0)
        assert err.timeout == 30.0
        assert err.details.get("timeout") == 30.0

    def test_prompt_error(self):
        """Test prompt error."""
        err = PromptError("failed", session_id="sess-1")
        assert err.session_id == "sess-1"
        assert err.code == "PROMPT_ERROR"


# ============================================================================
# Test ResponseChunk
# ============================================================================


class TestResponseChunk:
    """Test ResponseChunk class."""

    def test_basic_chunk(self):
        """Test basic chunk creation."""
        chunk = ResponseChunk(content="hello", chunk_type="text")
        assert chunk.content == "hello"
        assert chunk.chunk_type == "text"
        assert chunk.done is False
        assert chunk.metadata == {}

    def test_done_chunk(self):
        """Test done chunk."""
        chunk = ResponseChunk(content="", chunk_type="complete", done=True)
        assert chunk.done is True

    def test_chunk_with_metadata(self):
        """Test chunk with metadata."""
        meta = {"tool_name": "read_file", "call_id": "123"}
        chunk = ResponseChunk(content="result", chunk_type="tool_result", metadata=meta)
        assert chunk.metadata == meta

    def test_chunk_repr(self):
        """Test chunk representation."""
        chunk = ResponseChunk(content="hello world", done=True)
        repr_str = repr(chunk)
        assert "ResponseChunk" in repr_str
        assert "done=True" in repr_str


# ============================================================================
# Test AMCPClient
# ============================================================================


class TestAMCPClient:
    """Test AMCPClient class."""

    def test_remote_mode_creation(self):
        """Test creating client in remote mode."""
        client = AMCPClient.remote("http://localhost:4096")
        assert client.mode == ClientMode.REMOTE
        assert client.url == "http://localhost:4096"
        assert client.is_connected is False

    def test_embedded_mode_creation(self):
        """Test creating client in embedded mode."""
        client = AMCPClient.embedded()
        assert client.mode == ClientMode.EMBEDDED
        assert client.url is None

    def test_auto_mode_with_url(self):
        """Test auto mode with URL defaults to remote."""
        client = AMCPClient.auto("http://localhost:4096")
        assert client.mode == ClientMode.REMOTE

    def test_auto_mode_without_url(self):
        """Test auto mode without URL defaults to embedded."""
        client = AMCPClient.auto()
        assert client.mode == ClientMode.EMBEDDED

    def test_url_based_mode_detection(self):
        """Test that URL presence determines mode."""
        with_url = AMCPClient("http://localhost:4096")
        assert with_url.mode == ClientMode.REMOTE

        without_url = AMCPClient()
        assert without_url.mode == ClientMode.EMBEDDED


# ============================================================================
# Test HTTPClient
# ============================================================================


class TestHTTPClient:
    """Test HTTPClient class."""

    def test_client_creation(self):
        """Test client creation."""
        client = HTTPClient("http://localhost:4096")
        assert client._url == "http://localhost:4096"
        assert client.base_url == "http://localhost:4096/api/v1"
        assert client.is_connected is False

    def test_url_trailing_slash(self):
        """Test URL normalization."""
        client = HTTPClient("http://localhost:4096/")
        assert client._url == "http://localhost:4096"

    def test_ensure_connected_raises(self):
        """Test that ensure_connected raises when not connected."""
        client = HTTPClient("http://localhost:4096")
        with pytest.raises(ConnectionError):
            client._ensure_connected()


# ============================================================================
# Test EmbeddedClient
# ============================================================================


class TestEmbeddedClient:
    """Test EmbeddedClient class."""

    @pytest.mark.asyncio
    async def test_connect_and_close(self):
        """Test connect and close."""
        client = EmbeddedClient()
        assert client.is_connected is False

        await client.connect()
        assert client.is_connected is True

        await client.close()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        async with EmbeddedClient() as client:
            assert client.is_connected is True
        # After exit, would be closed

    @pytest.mark.asyncio
    async def test_health(self):
        """Test health check."""
        async with EmbeddedClient() as client:
            health = await client.health()
            assert health["healthy"] is True
            assert "version" in health
            assert health["mode"] == "embedded"

    @pytest.mark.asyncio
    async def test_info(self):
        """Test info endpoint."""
        async with EmbeddedClient() as client:
            info = await client.info()
            assert info["name"] == "amcp-embedded"
            assert info["mode"] == "embedded"
            assert "capabilities" in info

    @pytest.mark.asyncio
    async def test_create_session(self):
        """Test session creation."""
        async with EmbeddedClient() as client:
            session = await client.create_session()
            assert "id" in session
            assert "cwd" in session
            assert "agent_name" in session

    @pytest.mark.asyncio
    async def test_create_session_with_cwd(self):
        """Test session creation with working directory."""
        async with EmbeddedClient() as client:
            session = await client.create_session(cwd="/tmp")
            assert session["cwd"] == "/tmp"

    @pytest.mark.asyncio
    async def test_get_session(self):
        """Test getting session."""
        async with EmbeddedClient() as client:
            created = await client.create_session()
            fetched = await client.get_session(created["id"])
            assert fetched["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        """Test getting non-existent session."""
        async with EmbeddedClient() as client:
            with pytest.raises(SessionNotFoundError):
                await client.get_session("non-existent")

    @pytest.mark.asyncio
    async def test_list_sessions(self):
        """Test listing sessions."""
        async with EmbeddedClient() as client:
            # Start with empty
            sessions = await client.list_sessions()
            assert len(sessions) == 0

            # Create one
            await client.create_session()
            sessions = await client.list_sessions()
            assert len(sessions) == 1

    @pytest.mark.asyncio
    async def test_delete_session(self):
        """Test deleting session."""
        async with EmbeddedClient() as client:
            session = await client.create_session()
            await client.delete_session(session["id"])

            sessions = await client.list_sessions()
            assert len(sessions) == 0

    @pytest.mark.asyncio
    async def test_delete_session_not_found(self):
        """Test deleting non-existent session."""
        async with EmbeddedClient() as client:
            with pytest.raises(SessionNotFoundError):
                await client.delete_session("non-existent")

    @pytest.mark.asyncio
    async def test_list_tools(self):
        """Test listing tools."""
        async with EmbeddedClient() as client:
            tools = await client.list_tools()
            assert isinstance(tools, list)
            # Should have at least some default tools
            assert len(tools) > 0
            # Each tool should have a name
            for tool in tools:
                assert "name" in tool

    @pytest.mark.asyncio
    async def test_list_agents(self):
        """Test listing agents."""
        async with EmbeddedClient() as client:
            agents = await client.list_agents()
            assert isinstance(agents, list)
            # Should have at least some agents
            assert len(agents) > 0
            for agent in agents:
                assert "name" in agent


# ============================================================================
# Test ClientSession
# ============================================================================


class TestClientSession:
    """Test ClientSession class."""

    @pytest.mark.asyncio
    async def test_session_properties(self):
        """Test session properties."""
        async with EmbeddedClient() as client:
            session_data = await client.create_session()
            session = ClientSession(
                client=client,
                session_id=session_data["id"],
                cwd=session_data.get("cwd"),
                agent_name=session_data.get("agent_name"),
            )

            assert session.session_id == session_data["id"]
            assert session.id == session_data["id"]  # Alias
            assert session.cwd == session_data.get("cwd")

    @pytest.mark.asyncio
    async def test_session_info(self):
        """Test getting session info."""
        async with EmbeddedClient() as client:
            session_data = await client.create_session()
            session = ClientSession(
                client=client,
                session_id=session_data["id"],
            )

            info = await session.info()
            assert info["id"] == session_data["id"]

    @pytest.mark.asyncio
    async def test_session_delete(self):
        """Test session deletion."""
        async with EmbeddedClient() as client:
            session_data = await client.create_session()
            session = ClientSession(
                client=client,
                session_id=session_data["id"],
            )

            await session.delete()

            # Should be deleted
            with pytest.raises(SessionNotFoundError):
                await client.get_session(session_data["id"])

    def test_session_repr(self):
        """Test session representation."""
        # Mock client - we just need the repr
        session = ClientSession(
            client=None,  # type: ignore
            session_id="test-123",
            agent_name="coder",
        )
        repr_str = repr(session)
        assert "ClientSession" in repr_str
        assert "test-123" in repr_str
        assert "coder" in repr_str


# ============================================================================
# Integration-style tests (mocked)
# ============================================================================


class TestClientIntegration:
    """Integration-style tests with EmbeddedClient."""

    @pytest.mark.asyncio
    async def test_full_workflow_embedded(self):
        """Test full workflow with embedded client."""
        client = AMCPClient.embedded()

        async with client:
            # Check health
            # Note: For embedded, we'd need to adapt this
            # health = await client.health()
            # assert health["healthy"]

            # Create session
            session = await client.create_session(cwd="/tmp")
            assert session.session_id is not None

            # Get session info
            info = await session.info()
            assert info["id"] == session.session_id

            # List sessions
            sessions = await client.list_sessions()
            assert len(sessions) >= 1

            # Delete session
            await session.delete()

            # Verify deletion
            remaining = await client.list_sessions()
            assert all(s["id"] != session.session_id for s in remaining)
