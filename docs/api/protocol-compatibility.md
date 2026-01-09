# AMCP Protocol Compatibility Guide

This document describes how AMCP handles different protocols and ensures consistent behavior across:

- **HTTP REST API** - Primary programmatic interface
- **WebSocket** - Real-time streaming communication
- **SSE (Server-Sent Events)** - One-way event streaming
- **ACP (Agent Client Protocol)** - IDE/editor integration

## Protocol Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AMCP Protocol Layer                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌────────────────┐                                                    │
│   │ ProtocolAdapter│  ← Unified conversion layer                        │
│   └───────┬────────┘                                                    │
│           │                                                              │
│     ┌─────┴─────┬─────────────┬─────────────┐                          │
│     ▼           ▼             ▼             ▼                          │
│ ┌──────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐                     │
│ │ HTTP │   │WebSocket│   │   SSE   │   │   ACP   │                     │
│ │ REST │   │         │   │         │   │         │                     │
│ └──────┘   └─────────┘   └─────────┘   └─────────┘                     │
│                                                                          │
│   Request/     Bidirectional   Server→Client   IDE Integration          │
│   Response     Streaming       Events          (Zed, VS Code, etc.)     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Unified Event Model

All protocols use a unified event model defined in `amcp.server.models.EventType`:

| Event Type | HTTP | WebSocket | SSE | ACP |
|------------|------|-----------|-----|-----|
| `session.created` | POST /sessions | ✓ | ✓ | new_session |
| `session.deleted` | DELETE /sessions/{id} | ✓ | ✓ | - |
| `message.chunk` | (streaming response) | ✓ | ✓ | agent_message |
| `message.complete` | (response end) | ✓ | ✓ | agent_response |
| `tool.call_start` | - | ✓ | ✓ | tool_call_start |
| `tool.call_complete` | - | ✓ | ✓ | tool_call_update |

## ProtocolAdapter

The `ProtocolAdapter` class provides unified conversion between protocols:

```python
from amcp.protocol import ProtocolAdapter, get_protocol_adapter

adapter = get_protocol_adapter()

# Convert ACP event to unified format
acp_event = {"session_update": "agent_message", "content": [...]}
server_event = adapter.from_acp_event(acp_event, session_id)

# Convert to WebSocket format
ws_message = adapter.to_ws_message(server_event, message_id)

# Convert to SSE format
sse_data = adapter.to_sse_data(server_event)

# Convert back to ACP format
acp_event = adapter.to_acp_event(server_event)
```

## Error Code Mapping

AMCP uses a unified error code system that maps to appropriate responses in each protocol:

### HTTP Status Mapping

| Error Code | HTTP Status | Description |
|------------|-------------|-------------|
| `BAD_REQUEST` | 400 | Invalid request format |
| `VALIDATION_ERROR` | 400 | Request validation failed |
| `UNAUTHORIZED` | 401 | Authentication required |
| `FORBIDDEN` | 403 | Access denied |
| `SESSION_NOT_FOUND` | 404 | Session not found |
| `TOOL_NOT_FOUND` | 404 | Tool not found |
| `SESSION_BUSY` | 409 | Session is busy |
| `INTERNAL_ERROR` | 500 | Internal server error |
| `TIMEOUT` | 504 | Operation timed out |

### Usage

```python
from amcp.protocol import ProtocolError, ErrorCode, SessionNotFoundError

# Raise unified error
raise SessionNotFoundError("session-123")

# Or manually
raise ProtocolError(
    code=ErrorCode.SESSION_BUSY,
    message="Session is processing another request",
    details={"session_id": "session-123"}
)
```

## ACP Protocol Mapping

### Session Updates

| ACP session_update | ServerEvent Type |
|--------------------|------------------|
| `agent_message` | `MESSAGE_CHUNK` |
| `agent_response` | `MESSAGE_COMPLETE` |
| `agent_thought` | `AGENT_THINKING` |
| `tool_call_start` | `TOOL_CALL_START` |
| `tool_call_update` | `TOOL_CALL_COMPLETE` |
| `current_mode_update` | `SESSION_STATUS_CHANGED` |
| `plan` | `AGENT_THINKING` |

### ACP Content Blocks

ACP uses content blocks in a specific format:

```json
{
  "session_update": "agent_message",
  "content": [
    {"type": "text", "text": "Hello, I'll help you..."}
  ]
}
```

The `ProtocolAdapter` extracts text from these blocks and normalizes them to our `ServerEvent.payload.content` format.

## WebSocket Message Format

### Request Messages

```json
{
  "type": "request",
  "id": "msg-123",
  "timestamp": "2026-01-08T12:00:00Z",
  "payload": {
    "action": "prompt",
    "content": "Help me refactor",
    "session_id": "session-abc"
  }
}
```

### Response Messages

```json
{
  "type": "response",
  "id": "msg-123",
  "timestamp": "2026-01-08T12:00:01Z",
  "payload": {
    "kind": "text",
    "content": "I'll help you...",
    "done": false,
    "session_id": "session-abc"
  }
}
```

### Event Messages

```json
{
  "type": "event",
  "timestamp": "2026-01-08T12:00:02Z",
  "payload": {
    "kind": "tool_call",
    "tool_name": "read_file",
    "arguments": {"path": "/src/main.py"},
    "session_id": "session-abc"
  }
}
```

## SSE Event Format

```
event: message.chunk
data: {"type":"message.chunk","session_id":"abc","payload":{"content":"Hello"}}

event: tool.call_start
data: {"type":"tool.call_start","session_id":"abc","payload":{"tool_name":"read_file"}}
```

## Best Practices

### 1. Use the ProtocolAdapter for conversions

Always use `ProtocolAdapter` instead of manual conversions to ensure consistency:

```python
from amcp.protocol import get_protocol_adapter

adapter = get_protocol_adapter()

# Good
ws_msg = adapter.to_ws_message(event)

# Bad - manual conversion
ws_msg = {"type": "event", "payload": event.payload}  # May miss fields
```

### 2. Use ProtocolError for errors

Unified error handling across protocols:

```python
from amcp.protocol import ProtocolError, ErrorCode

# Works correctly in HTTP, WebSocket, and SSE contexts
raise ProtocolError(ErrorCode.SESSION_NOT_FOUND, "Session not found")
```

### 3. Event factory methods

Use adapter factory methods for creating events:

```python
# Create message event
event = adapter.create_message_event(
    session_id="abc",
    content="Hello",
    done=False
)

# Create tool event
event = adapter.create_tool_start_event(
    session_id="abc",
    tool_name="read_file",
    arguments={"path": "/src/main.py"}
)
```

## Migration Guide

### From ACP-only to Multi-Protocol

1. **Import the adapter**:
   ```python
   from amcp.protocol import get_protocol_adapter
   ```

2. **Replace direct ACP events with unified events**:
   ```python
   # Before
   await conn.session_update(session_id, update=agent_message(...))
   
   # After
   adapter = get_protocol_adapter()
   event = adapter.create_message_event(session_id, content)
   # Event can be sent via any protocol
   ```

3. **Use unified error codes**:
   ```python
   # Before
   raise ValueError("Session not found")
   
   # After
   from amcp.protocol import SessionNotFoundError
   raise SessionNotFoundError(session_id)
   ```

## TypeScript Types

Generate TypeScript types for web clients:

```bash
# From running server
python scripts/generate_types.py --server http://localhost:4096

# Manual generation
python scripts/generate_types.py --manual
```

This generates `types/amcp-api.d.ts` with all API types.
