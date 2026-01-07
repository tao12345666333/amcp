"""Tests for AMCP Server module."""

import pytest
from fastapi.testclient import TestClient

from amcp.server import create_app, ServerConfig
from amcp.server.session_manager import (
    SessionManager,
    ManagedSession,
    SessionNotFoundError,
    MaxSessionsReachedError,
)


@pytest.fixture
def server_config():
    """Create a test server configuration."""
    return ServerConfig(
        host="127.0.0.1",
        port=4096,
        max_sessions=5,
    )


@pytest.fixture
def app(server_config):
    """Create a test FastAPI application."""
    return create_app(server_config)


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def session_manager(server_config):
    """Create a fresh session manager for testing."""
    return SessionManager(server_config)


class TestHealthEndpoints:
    """Test health and info endpoints."""

    def test_root_endpoint(self, client):
        """Test root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "amcp-server"
        assert "version" in data
        assert data["api"] == "/api/v1"

    def test_health_endpoint(self, client):
        """Test health endpoint returns healthy status."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["healthy"] is True
        assert "version" in data
        assert "uptime_seconds" in data

    def test_info_endpoint(self, client):
        """Test info endpoint returns server info."""
        response = client.get("/api/v1/info")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "amcp-server"
        assert "capabilities" in data
        assert "sessions" in data["capabilities"]


class TestSessionEndpoints:
    """Test session management endpoints."""

    def test_create_session(self, client):
        """Test creating a new session."""
        response = client.post("/api/v1/sessions", json={"cwd": "/tmp"})
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["cwd"] == "/tmp"
        assert data["status"] == "idle"

    def test_list_sessions(self, client):
        """Test listing sessions."""
        # Create a session first
        client.post("/api/v1/sessions", json={"cwd": "/tmp"})

        response = client.get("/api/v1/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "total" in data
        assert data["total"] >= 1

    def test_get_session(self, client):
        """Test getting a specific session."""
        # Create a session
        create_resp = client.post("/api/v1/sessions", json={"cwd": "/tmp"})
        session_id = create_resp.json()["id"]

        # Get the session
        response = client.get(f"/api/v1/sessions/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == session_id

    def test_get_nonexistent_session(self, client):
        """Test getting a nonexistent session returns 404."""
        response = client.get("/api/v1/sessions/nonexistent-id")
        assert response.status_code == 404

    def test_delete_session(self, client):
        """Test deleting a session."""
        # Create a session
        create_resp = client.post("/api/v1/sessions", json={"cwd": "/tmp"})
        session_id = create_resp.json()["id"]

        # Delete the session
        response = client.delete(f"/api/v1/sessions/{session_id}")
        assert response.status_code == 200

        # Verify it's deleted
        get_resp = client.get(f"/api/v1/sessions/{session_id}")
        assert get_resp.status_code == 404


class TestToolEndpoints:
    """Test tool management endpoints."""

    def test_list_tools(self, client):
        """Test listing available tools."""
        response = client.get("/api/v1/tools")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "total" in data
        assert len(data["tools"]) > 0

    def test_get_tool(self, client):
        """Test getting a specific tool."""
        response = client.get("/api/v1/tools/read_file")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "read_file"

    def test_get_nonexistent_tool(self, client):
        """Test getting a nonexistent tool returns 404."""
        response = client.get("/api/v1/tools/nonexistent_tool")
        assert response.status_code == 404


class TestAgentEndpoints:
    """Test agent management endpoints."""

    def test_list_agents(self, client):
        """Test listing available agents."""
        response = client.get("/api/v1/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "total" in data
        assert len(data["agents"]) > 0

    def test_get_agent(self, client):
        """Test getting a specific agent."""
        response = client.get("/api/v1/agents/coder")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "coder"
        assert data["mode"] == "primary"

    def test_get_nonexistent_agent(self, client):
        """Test getting a nonexistent agent returns 404."""
        response = client.get("/api/v1/agents/nonexistent_agent")
        assert response.status_code == 404


class TestSessionManager:
    """Test session manager functionality."""

    @pytest.mark.asyncio
    async def test_create_session(self, session_manager):
        """Test creating a session via manager."""
        session = await session_manager.create_session(cwd="/tmp")
        assert session.id.startswith("session-")
        assert session.cwd == "/tmp"
        assert session_manager.session_count == 1

    @pytest.mark.asyncio
    async def test_get_session(self, session_manager):
        """Test getting a session by ID."""
        created = await session_manager.create_session(cwd="/tmp")
        retrieved = await session_manager.get_session(created.id)
        assert retrieved.id == created.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, session_manager):
        """Test getting a nonexistent session raises error."""
        with pytest.raises(SessionNotFoundError):
            await session_manager.get_session("nonexistent-id")

    @pytest.mark.asyncio
    async def test_delete_session(self, session_manager):
        """Test deleting a session."""
        session = await session_manager.create_session(cwd="/tmp")
        await session_manager.delete_session(session.id)
        assert session_manager.session_count == 0

    @pytest.mark.asyncio
    async def test_max_sessions_limit(self, session_manager):
        """Test max sessions limit is enforced."""
        # Create max sessions
        for i in range(5):
            await session_manager.create_session(cwd="/tmp")

        # Try to create one more
        with pytest.raises(MaxSessionsReachedError):
            await session_manager.create_session(cwd="/tmp")

    @pytest.mark.asyncio
    async def test_list_sessions(self, session_manager):
        """Test listing all sessions."""
        await session_manager.create_session(cwd="/tmp")
        await session_manager.create_session(cwd="/var")

        sessions = await session_manager.list_sessions()
        assert len(sessions) == 2
