# AMCP Phase 10: Anchor (Session Tracking)

A lightweight session tracking mechanism that captures structured snapshots of agent execution, enabling replay, debugging, auditing, and recovery of agent sessions.

## Motivation

Today, AMCP's Memory system captures high-level conversation summaries, and the Event Bus provides real-time event streams. However, neither provides a persistent, structured record of **exactly what happened** during a session. Anchor fills this gap:

- **Debugging**: Understand why an agent made a specific decision or which tool calls led to an error
- **Auditing**: Maintain a verifiable record of all agent actions for compliance
- **Recovery**: Resume interrupted sessions from the last known good state
- **Learning**: Analyze execution patterns to improve agent performance
- **Collaboration**: Share session traces with team members for review

### Anchor vs. Memory vs. Events

| Feature | Memory | Event Bus | Anchor |
|---------|--------|-----------|--------|
| **Granularity** | Session summary | Real-time events | Step-by-step trace |
| **Persistence** | Markdown files | In-memory (lost) | Structured JSON |
| **Purpose** | Cross-session knowledge | Live monitoring | Post-hoc analysis |
| **Content** | What was discussed | What happened now | What happened & why |
| **Scope** | User/Project | Session lifetime | Per-session file |

## Architecture

### High-Level Design

```
┌────────────────────────────────────────────────────────┐
│                    Agent Execution                      │
│                                                        │
│   Step 1        Step 2        Step 3        Step N     │
│  [Prompt] → [Tool Call] → [Tool Call] → [Response]    │
│      │            │            │             │         │
│      ▼            ▼            ▼             ▼         │
│  ┌──────────────────────────────────────────────────┐  │
│  │              AnchorRecorder                       │  │
│  │  Records each step as an AnchorPoint              │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     │                                  │
│              ┌──────▼──────┐                           │
│              │ Anchor File │                           │
│              │  (JSON/JSONL)│                           │
│              └─────────────┘                           │
└────────────────────────────────────────────────────────┘
```

### Component Breakdown

```
src/amcp/
├── anchor/
│   ├── __init__.py
│   ├── recorder.py       # AnchorRecorder: captures execution steps
│   ├── models.py         # AnchorPoint, AnchorTrace data models
│   ├── storage.py        # AnchorStorage: file persistence
│   ├── viewer.py         # AnchorViewer: CLI trace viewing
│   └── analyzer.py       # AnchorAnalyzer: pattern analysis
```

## Core Concepts

### AnchorPoint

An AnchorPoint is a single recorded step in the agent's execution:

```python
@dataclass
class AnchorPoint:
    """A single point in the agent's execution trace."""

    # Identity
    id: str                          # Unique point ID (uuid)
    sequence: int                    # Sequence number within trace
    timestamp: datetime              # When this point was recorded

    # Classification
    type: AnchorPointType            # What kind of step this is
    phase: ExecutionPhase            # Which phase of execution

    # Content
    input: str | None                # Input to this step
    output: str | None               # Output from this step
    metadata: dict[str, Any]         # Additional context

    # Metrics
    duration_ms: float | None        # How long this step took
    tokens_used: int | None          # Tokens consumed
    cost_usd: float | None           # Estimated cost

    # Relationships
    parent_id: str | None            # Parent point (for nested calls)
    children_ids: list[str]          # Child points
```

### AnchorPointType

```python
class AnchorPointType(StrEnum):
    """Types of anchor points."""

    # User interaction
    USER_INPUT = "user_input"                # User sent a message
    AGENT_RESPONSE = "agent_response"        # Agent sent a response

    # LLM interaction
    LLM_REQUEST = "llm_request"              # Request sent to LLM
    LLM_RESPONSE = "llm_response"            # Response from LLM

    # Tool execution
    TOOL_CALL = "tool_call"                  # Tool was called
    TOOL_RESULT = "tool_result"              # Tool returned result

    # Agent lifecycle
    SESSION_START = "session_start"          # Session started
    SESSION_END = "session_end"              # Session ended
    COMPACTION = "compaction"                # Context was compacted

    # Control flow
    DECISION = "decision"                    # Agent made a decision
    ERROR = "error"                          # An error occurred
    RETRY = "retry"                          # A retry was attempted
```

### ExecutionPhase

```python
class ExecutionPhase(StrEnum):
    """Phases of agent execution."""
    INIT = "init"                # Session initialization
    PROMPT = "prompt"            # Processing user prompt
    PLANNING = "planning"        # Agent planning next steps
    EXECUTION = "execution"      # Executing tool calls
    SYNTHESIS = "synthesis"      # Synthesizing final response
    CLEANUP = "cleanup"          # Post-execution cleanup
```

### AnchorTrace

An AnchorTrace is the complete record of a session:

```python
@dataclass
class AnchorTrace:
    """Complete execution trace for a session."""

    # Identity
    trace_id: str                    # Unique trace ID
    session_id: str                  # Associated AMCP session

    # Context
    agent_name: str                  # Agent that executed
    model: str                       # LLM model used
    started_at: datetime             # When session started
    ended_at: datetime | None        # When session ended
    work_dir: str                    # Working directory

    # Content
    points: list[AnchorPoint]        # Ordered list of anchor points
    user_prompt: str                 # Original user prompt

    # Aggregate metrics
    total_duration_ms: float         # Total execution time
    total_tokens: int                # Total tokens consumed
    total_cost_usd: float            # Estimated total cost
    tool_calls_count: int            # Number of tool calls
    llm_calls_count: int             # Number of LLM API calls
    error_count: int                 # Number of errors

    # Status
    status: str                      # "completed" | "error" | "interrupted"
    error_message: str | None        # If status is "error"
```

## Implementation Details

### AnchorRecorder

```python
class AnchorRecorder:
    """Records agent execution as anchor points."""

    def __init__(self, session_id: str, storage: AnchorStorage):
        self.session_id = session_id
        self.storage = storage
        self.trace = AnchorTrace(
            trace_id=str(uuid4()),
            session_id=session_id,
            points=[],
            started_at=datetime.now(),
            ...
        )
        self._sequence = 0
        self._stack: list[str] = []  # Parent ID stack for nesting

    def record(
        self,
        type: AnchorPointType,
        phase: ExecutionPhase,
        input: str | None = None,
        output: str | None = None,
        metadata: dict | None = None,
        duration_ms: float | None = None,
        tokens_used: int | None = None,
    ) -> AnchorPoint:
        """Record a single anchor point."""
        point = AnchorPoint(
            id=str(uuid4()),
            sequence=self._sequence,
            timestamp=datetime.now(),
            type=type,
            phase=phase,
            input=input,
            output=output,
            metadata=metadata or {},
            duration_ms=duration_ms,
            tokens_used=tokens_used,
            parent_id=self._stack[-1] if self._stack else None,
            children_ids=[],
        )
        self._sequence += 1
        self.trace.points.append(point)

        # Append to parent's children
        if point.parent_id:
            parent = self._find_point(point.parent_id)
            if parent:
                parent.children_ids.append(point.id)

        # Stream to storage (for crash recovery)
        self.storage.append_point(self.trace.trace_id, point)

        return point

    @contextmanager
    def span(self, type: AnchorPointType, phase: ExecutionPhase, **kwargs):
        """Context manager for recording a span with duration."""
        start = time.perf_counter()
        point = self.record(type=type, phase=phase, **kwargs)
        self._stack.append(point.id)
        try:
            yield point
        finally:
            self._stack.pop()
            point.duration_ms = (time.perf_counter() - start) * 1000

    def finalize(self):
        """Finalize and save the complete trace."""
        self.trace.ended_at = datetime.now()
        self.trace.total_duration_ms = (
            (self.trace.ended_at - self.trace.started_at).total_seconds() * 1000
        )
        self.trace.tool_calls_count = sum(
            1 for p in self.trace.points if p.type == AnchorPointType.TOOL_CALL
        )
        self.trace.llm_calls_count = sum(
            1 for p in self.trace.points if p.type == AnchorPointType.LLM_REQUEST
        )
        self.storage.save_trace(self.trace)
```

### Agent Integration

```python
class Agent:
    async def _process_message(self, user_input, work_dir, stream, show_progress):
        """Process message with anchor recording."""
        # Start recording
        recorder = AnchorRecorder(self.session_id, self.anchor_storage)

        # Record user input
        recorder.record(
            type=AnchorPointType.USER_INPUT,
            phase=ExecutionPhase.PROMPT,
            input=user_input,
        )

        try:
            for step in range(self.max_steps):
                # Record LLM call
                with recorder.span(
                    type=AnchorPointType.LLM_REQUEST,
                    phase=ExecutionPhase.PLANNING,
                    input=f"Messages: {len(self.conversation_history)}",
                ) as llm_point:
                    response = await self._call_llm(messages)
                    llm_point.output = response.content[:500]
                    llm_point.tokens_used = response.usage.total_tokens

                # Record tool calls
                for tool_call in response.tool_calls:
                    with recorder.span(
                        type=AnchorPointType.TOOL_CALL,
                        phase=ExecutionPhase.EXECUTION,
                        input=json.dumps({
                            "tool": tool_call.name,
                            "args": tool_call.arguments,
                        }),
                    ) as tool_point:
                        result = await self._execute_tool(tool_call)
                        tool_point.output = result.content[:500]
                        tool_point.metadata["success"] = result.success

            # Record final response
            recorder.record(
                type=AnchorPointType.AGENT_RESPONSE,
                phase=ExecutionPhase.SYNTHESIS,
                output=final_response,
            )

        except Exception as e:
            recorder.record(
                type=AnchorPointType.ERROR,
                phase=ExecutionPhase.EXECUTION,
                output=str(e),
            )
        finally:
            recorder.finalize()
```

### Storage

```python
class AnchorStorage:
    """Persist anchor traces to disk."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(".amcp/anchors")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def append_point(self, trace_id: str, point: AnchorPoint):
        """Append a point to the streaming JSONL file."""
        path = self.base_dir / f"{trace_id}.jsonl"
        with path.open("a") as f:
            f.write(json.dumps(point.to_dict()) + "\n")

    def save_trace(self, trace: AnchorTrace):
        """Save the complete trace as a JSON file."""
        path = self.base_dir / f"{trace.trace_id}.json"
        path.write_text(json.dumps(trace.to_dict(), indent=2))

        # Clean up streaming file
        jsonl_path = self.base_dir / f"{trace.trace_id}.jsonl"
        jsonl_path.unlink(missing_ok=True)

    def load_trace(self, trace_id: str) -> AnchorTrace:
        """Load a trace from disk."""
        path = self.base_dir / f"{trace_id}.json"
        data = json.loads(path.read_text())
        return AnchorTrace.from_dict(data)

    def list_traces(
        self,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[AnchorTraceSummary]:
        """List available traces."""
        traces = []
        for path in sorted(self.base_dir.glob("*.json"), reverse=True):
            data = json.loads(path.read_text())
            if session_id and data["session_id"] != session_id:
                continue
            traces.append(AnchorTraceSummary(
                trace_id=data["trace_id"],
                session_id=data["session_id"],
                started_at=data["started_at"],
                status=data["status"],
                duration_ms=data["total_duration_ms"],
                tool_calls=data["tool_calls_count"],
                llm_calls=data["llm_calls_count"],
                prompt_preview=data["user_prompt"][:80],
            ))
            if len(traces) >= limit:
                break
        return traces

    def cleanup(self, max_age_days: int = 30):
        """Remove traces older than max_age_days."""
        cutoff = datetime.now() - timedelta(days=max_age_days)
        for path in self.base_dir.glob("*.json"):
            data = json.loads(path.read_text())
            if datetime.fromisoformat(data["started_at"]) < cutoff:
                path.unlink()
```

## CLI Integration

### Viewing Traces

```bash
# List recent traces
amcp anchor list

# Output:
#   TRACE ID    SESSION           STARTED          STATUS     DURATION  TOOLS  LLMs  PROMPT
#   a1b2c3..    main-session      2026-02-14 09:20  ✅ done     8.2s       5      3    Check CI status for...
#   d4e5f6..    test-memory       2026-02-14 09:19  ✅ done     3.1s       2      2    Write project memory...
#   g7h8i9..    debug-session     2026-02-14 08:45  ❌ error    12.5s      8      6    Fix the login bug...

# View a specific trace
amcp anchor view a1b2c3

# Output:
#   Trace: a1b2c3 | Session: main-session | Duration: 8.2s
#   Model: gpt-4-turbo | Tokens: 12,340 | Cost: $0.04
#
#   Timeline:
#   ──────────────────────────────────────────────────────
#   [0.0s]  📥 USER_INPUT
#           "Check CI status for all open PRs"
#
#   [0.1s]  🤖 LLM_REQUEST (planning)
#           Messages: 3 | Tokens: 1,200
#
#   [0.8s]  🔧 TOOL_CALL bash
#           $ gh pr list --state open
#           → Found 2 open PRs
#
#   [2.1s]  🔧 TOOL_CALL bash
#           $ gh pr checks 4
#           → All checks passed ✅
#
#   [3.5s]  🔧 TOOL_CALL bash
#           $ gh pr checks 5
#           → 1 failing check ❌
#
#   [4.2s]  🤖 LLM_REQUEST (analysis)
#           Messages: 7 | Tokens: 3,400
#
#   [5.8s]  🔧 TOOL_CALL memory (write)
#           Logged CI check results
#
#   [7.9s]  🤖 LLM_REQUEST (synthesis)
#           Messages: 9 | Tokens: 2,100
#
#   [8.2s]  📤 AGENT_RESPONSE
#           "CI Status: PR #4 ✅, PR #5 ❌ (lint failure)"
#   ──────────────────────────────────────────────────────

# Filter traces by session
amcp anchor list --session main-session

# View only tool calls in a trace
amcp anchor view a1b2c3 --tools-only

# Export trace as JSON
amcp anchor export a1b2c3 --output trace.json

# Cleanup old traces
amcp anchor cleanup --older-than 30d
```

### Interactive Trace Explorer

```bash
# Open interactive TUI trace explorer
amcp anchor explore a1b2c3

# Features:
# - Expand/collapse nested spans
# - Filter by point type
# - View full input/output for each point
# - Timeline visualization
# - Cost breakdown
```

## Configuration

```toml
[anchor]
enabled = true                    # Enable anchor recording
storage_dir = ".amcp/anchors"    # Where to store traces
max_traces = 100                 # Max traces to keep
max_age_days = 30                # Auto-cleanup after N days

# What to record
record_llm_requests = true       # Record LLM request details
record_llm_responses = true      # Record LLM responses
record_tool_inputs = true        # Record tool input arguments
record_tool_outputs = true       # Record tool output results
max_content_length = 2000        # Truncate content at N chars

# Privacy
redact_secrets = true            # Redact API keys, tokens, etc.
redact_patterns = [              # Custom redaction patterns
    "Bearer .*",
    "token=.*",
]
```

## Recovery from Interruption

Anchor enables session recovery when the agent is interrupted:

```python
class AnchorRecovery:
    """Recover interrupted sessions from anchor points."""

    def get_recovery_context(self, trace_id: str) -> str:
        """Generate recovery context from an interrupted trace."""
        # Load the streaming JSONL (incomplete trace)
        points = self._load_streaming_points(trace_id)

        context = "## Session Recovery Context\n\n"
        context += f"Your previous session was interrupted. Here's what happened:\n\n"

        for point in points:
            if point.type == AnchorPointType.USER_INPUT:
                context += f"User asked: {point.input}\n\n"
            elif point.type == AnchorPointType.TOOL_CALL:
                tool_info = json.loads(point.input)
                context += f"You called `{tool_info['tool']}` "
                if point.output:
                    context += f"and got: {point.output[:200]}\n"
                else:
                    context += "(no result recorded - this call may have been interrupted)\n"
            elif point.type == AnchorPointType.AGENT_RESPONSE:
                context += f"You responded: {point.output[:300]}\n\n"

        context += "\nPlease continue from where you left off.\n"
        return context

    async def resume_session(self, trace_id: str, agent: Agent) -> str:
        """Resume an interrupted session."""
        recovery_context = self.get_recovery_context(trace_id)
        return await agent.run(
            f"[RECOVERY] {recovery_context}\n\n"
            f"Please continue the original task.",
            work_dir=Path(trace.work_dir),
        )
```

### CLI Recovery

```bash
# List interrupted sessions
amcp anchor list --status interrupted

# Resume an interrupted session
amcp anchor resume g7h8i9

# Output:
#   🔄 Resuming session from trace g7h8i9...
#   Recovery context: 6 anchor points loaded
#   Original prompt: "Fix the login bug..."
#   Last action: TOOL_CALL write_file (interrupted)
#
#   Agent: Continuing from where we left off...
```

## Analyzer

```python
class AnchorAnalyzer:
    """Analyze anchor traces for patterns and insights."""

    def summarize_trace(self, trace: AnchorTrace) -> dict:
        """Generate a summary of a trace."""
        return {
            "total_duration": trace.total_duration_ms,
            "llm_calls": trace.llm_calls_count,
            "tool_calls": trace.tool_calls_count,
            "tokens_used": trace.total_tokens,
            "estimated_cost": trace.total_cost_usd,
            "most_used_tools": self._top_tools(trace),
            "error_rate": trace.error_count / max(len(trace.points), 1),
            "avg_tool_duration": self._avg_tool_duration(trace),
            "decision_points": self._count_decisions(trace),
        }

    def compare_traces(self, trace_a: str, trace_b: str) -> dict:
        """Compare two traces for similar tasks."""
        a = self.storage.load_trace(trace_a)
        b = self.storage.load_trace(trace_b)
        return {
            "duration_diff": b.total_duration_ms - a.total_duration_ms,
            "token_diff": b.total_tokens - a.total_tokens,
            "tool_overlap": self._tool_overlap(a, b),
            "efficiency": "improved" if b.total_tokens < a.total_tokens else "regressed",
        }

    def usage_report(self, days: int = 7) -> dict:
        """Generate a usage report over the given period."""
        traces = self.storage.list_traces(limit=1000)
        cutoff = datetime.now() - timedelta(days=days)
        recent = [t for t in traces if t.started_at > cutoff]
        return {
            "total_sessions": len(recent),
            "total_tokens": sum(t.total_tokens for t in recent),
            "total_cost": sum(t.total_cost for t in recent),
            "avg_duration": sum(t.duration_ms for t in recent) / max(len(recent), 1),
            "success_rate": sum(1 for t in recent if t.status == "completed") / max(len(recent), 1),
            "top_tools": self._aggregate_tools(recent),
        }
```

### CLI Analytics

```bash
# Usage report
amcp anchor report --days 7

# Output:
#   📊 Anchor Report (Last 7 days)
#   ──────────────────────────
#   Sessions: 42
#   Total tokens: 234,567
#   Estimated cost: $2.34
#   Avg duration: 12.3s
#   Success rate: 95.2%
#
#   Top Tools:
#     1. bash (128 calls)
#     2. read_file (87 calls)
#     3. write_file (34 calls)
#     4. grep_search (29 calls)
#     5. memory (18 calls)
```

## Dependencies

No additional dependencies required. Anchor uses only Python standard library (`json`, `datetime`, `uuid`, `dataclasses`).

## Testing Strategy

```python
class TestAnchorRecorder:
    def test_record_point(self): ...
    def test_span_context_manager(self): ...
    def test_nested_spans(self): ...
    def test_finalize_trace(self): ...

class TestAnchorStorage:
    def test_append_point(self): ...
    def test_save_and_load_trace(self): ...
    def test_list_traces(self): ...
    def test_cleanup(self): ...

class TestAnchorRecovery:
    def test_recovery_context(self): ...
    def test_resume_session(self): ...

class TestAnchorAnalyzer:
    def test_summarize_trace(self): ...
    def test_compare_traces(self): ...
    def test_usage_report(self): ...
```

## Version

Anchor is planned for **AMCP v0.13.0**.
