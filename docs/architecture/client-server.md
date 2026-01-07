# AMCP Client-Server Architecture Design

> **Version**: 1.0.0  
> **Created**: 2026-01-07  
> **Status**: Draft

## Overview

This document describes the Client-Server (C/S) architecture for AMCP, enabling remote control, multiple client types (CLI, TUI, Web, Desktop, Mobile), and better separation of concerns.

## Goals

1. **Decouple UI from Core Logic**: Allow the agent engine to run independently of any specific UI
2. **Enable Remote Access**: Control AMCP from different machines or devices
3. **Support Multiple Clients**: CLI, TUI (Toad), Web UI, Desktop App, Mobile App
4. **Maintain CLI Compatibility**: Existing `amcp` commands continue to work seamlessly
5. **Leverage Existing Infrastructure**: Build on top of existing ACP support

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AMCP Client-Server Architecture                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   CLIENTS                                                                    │
│   ─────────────────────────────────────────────────────────────────────     │
│                                                                              │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│   │  CLI Client  │  │  TUI Client  │  │  Web Client  │  │Desktop Client│    │
│   │ amcp attach  │  │  amcp tui    │  │  (React/Vue) │  │  (Tauri)     │    │
│   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│          │                 │                 │                 │            │
│          └─────────────────┴────────┬────────┴─────────────────┘            │
│                                     │                                        │
│   TRANSPORT LAYER                   │                                        │
│   ─────────────────────────────────────────────────────────────────────     │
│                      ┌──────────────▼──────────────┐                        │
│                      │      Protocol Options       │                        │
│                      │  ────────────────────────   │                        │
│                      │  • HTTP REST API (primary)  │                        │
│                      │  • WebSocket (streaming)    │                        │
│                      │  • SSE (server events)      │                        │
│                      │  • ACP (existing, optional) │                        │
│                      └──────────────┬──────────────┘                        │
│                                     │                                        │
│   SERVER                            │                                        │
│   ─────────────────────────────────────────────────────────────────────     │
│                      ┌──────────────▼──────────────┐                        │
│                      │       AMCP Server           │                        │
│                      │  ────────────────────────   │                        │
│                      │  ┌────────────────────────┐ │                        │
│                      │  │    Session Manager     │ │                        │
│                      │  │  • Multi-client support│ │                        │
│                      │  │  • Session persistence │ │                        │
│                      │  └────────────────────────┘ │                        │
│                      │              │              │                        │
│                      │  ┌───────────▼────────────┐ │                        │
│                      │  │     Agent Engine       │ │                        │
│                      │  │  • Prompt processing   │ │                        │
│                      │  │  • Tool execution      │ │                        │
│                      │  │  • Response streaming  │ │                        │
│                      │  └────────────────────────┘ │                        │
│                      │              │              │                        │
│                      │  ┌───────────▼────────────┐ │                        │
│                      │  │    Core Components     │ │                        │
│                      │  │  • ToolRegistry        │ │                        │
│                      │  │  • MCP Client          │ │                        │
│                      │  │  • EventBus            │ │                        │
│                      │  │  • HooksManager        │ │                        │
│                      │  │  • MessageQueue        │ │                        │
│                      │  └────────────────────────┘ │                        │
│                      └─────────────────────────────┘                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## API Specification

### Base URL

```
http://{host}:{port}/api/v1
```

Default: `http://localhost:4096/api/v1`

### Authentication

Initial implementation: No authentication (local use only)

Future: API key or token-based authentication for remote access

### Endpoints

#### Health & Info

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server health check |
| GET | `/info` | Server and agent information |

#### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/sessions` | Create a new session |
| GET | `/sessions` | List all sessions |
| GET | `/sessions/{id}` | Get session details |
| DELETE | `/sessions/{id}` | Delete a session |
| POST | `/sessions/{id}/prompt` | Send a prompt to the session |
| POST | `/sessions/{id}/cancel` | Cancel current operation |

#### Events (SSE)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/events` | Global event stream |
| GET | `/sessions/{id}/events` | Session-specific event stream |

#### Tools

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/tools` | List available tools |
| POST | `/tools/{name}/execute` | Execute a tool directly |

#### Agents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/agents` | List available agents |
| GET | `/agents/{name}` | Get agent details |

### WebSocket API

#### Connection

```
ws://{host}:{port}/ws?session_id={session_id}
```

#### Message Format

All WebSocket messages follow this structure:

```json
{
  "type": "request|response|event|error",
  "id": "unique-message-id",
  "timestamp": "2026-01-07T12:00:00Z",
  "payload": { ... }
}
```

#### Message Types

**Client → Server:**

```json
// Prompt
{
  "type": "request",
  "id": "msg-123",
  "payload": {
    "action": "prompt",
    "content": "Help me refactor this code",
    "session_id": "session-abc"
  }
}

// Cancel
{
  "type": "request",
  "id": "msg-124",
  "payload": {
    "action": "cancel",
    "session_id": "session-abc"
  }
}
```

**Server → Client:**

```json
// Text response (streaming)
{
  "type": "response",
  "id": "msg-123",
  "payload": {
    "kind": "text",
    "content": "I'll help you refactor...",
    "done": false
  }
}

// Tool call
{
  "type": "event",
  "payload": {
    "kind": "tool_call",
    "tool_name": "read_file",
    "arguments": {"path": "/src/main.py"},
    "session_id": "session-abc"
  }
}

// Tool result
{
  "type": "event",
  "payload": {
    "kind": "tool_result",
    "tool_name": "read_file",
    "result": "file content...",
    "success": true
  }
}

// Completion
{
  "type": "response",
  "id": "msg-123",
  "payload": {
    "kind": "complete",
    "usage": {
      "prompt_tokens": 1234,
      "completion_tokens": 567
    }
  }
}
```

## Data Models

### Session

```python
class Session(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    cwd: str                    # Working directory
    agent_name: str             # Agent being used
    status: SessionStatus       # idle, busy, cancelled
    message_count: int
    token_usage: TokenUsage
```

### SessionStatus

```python
class SessionStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    CANCELLED = "cancelled"
    ERROR = "error"
```

### PromptRequest

```python
class PromptRequest(BaseModel):
    content: str
    priority: MessagePriority = MessagePriority.NORMAL
    stream: bool = True
```

### PromptResponse

```python
class PromptResponse(BaseModel):
    session_id: str
    message_id: str
    status: str  # "streaming" | "complete" | "error"
```

### Event

```python
class ServerEvent(BaseModel):
    type: EventType
    session_id: str | None
    timestamp: datetime
    payload: dict[str, Any]
```

### EventType

```python
class EventType(str, Enum):
    # Session events
    SESSION_CREATED = "session.created"
    SESSION_DELETED = "session.deleted"
    SESSION_STATUS_CHANGED = "session.status_changed"
    
    # Message events
    MESSAGE_START = "message.start"
    MESSAGE_CHUNK = "message.chunk"
    MESSAGE_COMPLETE = "message.complete"
    MESSAGE_ERROR = "message.error"
    
    # Tool events
    TOOL_CALL_START = "tool.call_start"
    TOOL_CALL_COMPLETE = "tool.call_complete"
    TOOL_CALL_ERROR = "tool.call_error"
    
    # Agent events
    AGENT_THINKING = "agent.thinking"
    AGENT_IDLE = "agent.idle"
```

## Implementation Plan

### Phase 1: Server Core (Week 1) ✅ COMPLETED

**Goal**: Basic HTTP server with session management

**Status**: ✅ Completed on 2026-01-07

**Implemented**:
1. ✅ Created `src/amcp/server/` module structure
2. ✅ Implemented FastAPI application with basic routes
3. ✅ Implemented session manager with async support
4. ✅ Added `amcp serve` command with host/port options
5. ✅ Added `amcp attach <url>` command for CLI client
6. ✅ Added health, info, and status endpoints
7. ✅ Added session CRUD operations with streaming support
8. ✅ Added tools and agents list endpoints
9. ✅ Added WebSocket handler framework
10. ✅ Added SSE event stream framework
11. ✅ Added 20 unit tests (all passing)

**Deliverables**:
- ✅ `amcp serve [--port] [--host] [--work-dir]` command
- ✅ `amcp attach <url> [--session] [--work-dir]` command
- ✅ `/api/v1/health`, `/api/v1/info` endpoints
- ✅ Session management endpoints (`/api/v1/sessions/*`)
- ✅ Tool listing endpoints (`/api/v1/tools/*`)
- ✅ Agent listing endpoints (`/api/v1/agents/*`)
- ✅ OpenAPI documentation at `/docs`

### Phase 2: Streaming & Events (Week 2)

**Goal**: Real-time communication

**Tasks**:
1. Implement SSE event stream
2. Implement WebSocket handler
3. Add streaming prompt responses
4. Integrate with existing EventBus
5. Add tool execution events

**Deliverables**:
- SSE endpoint for events
- WebSocket support for interactive sessions
- Real-time tool execution feedback

### Phase 3: CLI Client (Week 3)

**Goal**: CLI can connect to remote server

**Tasks**:
1. Create `src/amcp/client/` module
2. Implement HTTP client wrapper
3. Implement WebSocket client
4. Add `amcp attach <url>` command
5. Refactor existing CLI to use client SDK
6. Support both embedded and remote modes

**Deliverables**:
- `amcp attach <url>` command
- Client SDK for Python applications
- Seamless switching between embedded/remote modes

### Phase 4: Protocol Unification (Week 4)

**Goal**: Unified experience across protocols

**Tasks**:
1. Ensure ACP and HTTP APIs are consistent
2. Add OpenAPI documentation
3. Generate TypeScript types for web clients
4. Create protocol compatibility layer

**Deliverables**:
- OpenAPI spec at `/openapi.json`
- TypeScript type definitions
- Unified error handling

## Directory Structure

```
src/amcp/
├── __init__.py
├── cli.py                     # CLI entry (modified)
├── agent.py                   # Agent core (unchanged)
├── acp_agent.py              # ACP service (unchanged)
│
├── server/                    # NEW: Server module
│   ├── __init__.py
│   ├── app.py                # FastAPI application
│   ├── config.py             # Server configuration
│   ├── session_manager.py    # Session management
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── health.py         # Health endpoints
│   │   ├── sessions.py       # Session endpoints
│   │   ├── tools.py          # Tool endpoints
│   │   └── agents.py         # Agent endpoints
│   ├── websocket.py          # WebSocket handler
│   ├── events.py             # SSE event stream
│   └── models.py             # API models
│
├── client/                    # NEW: Client SDK
│   ├── __init__.py
│   ├── base.py               # Base client interface
│   ├── http_client.py        # HTTP REST client
│   ├── ws_client.py          # WebSocket client
│   └── embedded.py           # Embedded mode (current behavior)
│
└── ... (existing modules unchanged)
```

## CLI Commands

### New Commands

```bash
# Start server in headless mode
amcp serve [--port 4096] [--host 0.0.0.0]

# Connect to running server
amcp attach <url> [--session <id>]

# Example usage
amcp serve --port 4096
amcp attach http://localhost:4096 --session my-session
```

### Modified Commands

```bash
# Default behavior: embedded mode (unchanged)
amcp "help me with this code"

# Explicit mode selection
amcp --mode embedded "help me"     # Force embedded
amcp --mode remote --server http://... "help me"  # Force remote
```

## Configuration

### Server Configuration

```yaml
# ~/.config/amcp/server.yaml
server:
  host: "0.0.0.0"
  port: 4096
  cors_origins:
    - "http://localhost:*"
    - "tauri://localhost"
  auth:
    enabled: false
    # Future: API key support
```

### Client Configuration

```yaml
# ~/.config/amcp/config.yaml
client:
  default_server: "http://localhost:4096"
  timeout: 30
  retry_attempts: 3
```

## Security Considerations

1. **Local-only by default**: Server binds to `127.0.0.1` by default
2. **CORS**: Strict CORS policy for web clients
3. **Authentication**: API key support for remote access (Phase 4+)
4. **TLS**: HTTPS support for production deployments

## Compatibility

### Backward Compatibility

- All existing `amcp` commands work unchanged
- Existing ACP support (`amcp acp serve`) remains functional
- Configuration files are backward compatible

### Forward Compatibility

- API versioning (`/api/v1`) for future changes
- Extensible message format for new event types
- Plugin system for custom endpoints

## Testing Strategy

1. **Unit Tests**: Server components, session manager, models
2. **Integration Tests**: API endpoints, WebSocket communication
3. **E2E Tests**: CLI client ↔ Server interaction
4. **Load Tests**: Multiple concurrent clients

## Success Metrics

1. Server starts in < 500ms
2. API response time < 50ms (non-streaming)
3. WebSocket latency < 10ms
4. Support 10+ concurrent sessions
5. 100% backward compatibility with existing CLI

## References

- [OpenCode Architecture](https://github.com/sst/opencode)
- [ACP Specification](https://github.com/ArcadeAI/arcade-ai)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [WebSocket Best Practices](https://websockets.readthedocs.io/)
