# AMCP Phase 8: Background Services (Scheduler + Reactor + Health)

Enables AMCP to operate autonomously with scheduled tasks, periodic health
checks, and event-driven actions — transforming it from a reactive assistant
into a proactive agent.

## Motivation

Without Phase 8, AMCP only acts when a user sends a message. With background
services the agent can:

- **Run scheduled tasks**: Automatically check CI, review new PRs, monitor systems
- **Self-maintain**: Clean up old sessions, compact memory, update skills
- **React to events**: Trigger actions based on GitHub webhooks or custom events
- **Stay healthy**: Periodic health checks surface issues before they escalate
- **Evolve independently**: Combined with Skill Creator + Memory, enables a
  self-improving agent loop

### The Self-Evolution Loop

```
         ┌─────────────┐
         │   Observe    │ ◀── Cron checks environment
         └──────┬───────┘
                │
         ┌──────▼───────┐
         │   Remember   │ ◀── Memory logs findings
         └──────┬───────┘
                │
         ┌──────▼───────┐
         │    Learn     │ ◀── Creates/updates skills
         └──────┬───────┘
                │
         ┌──────▼───────┐
         │     Act      │ ◀── Executes improvements
         └──────┬───────┘
                │
                └──────────▶ (repeat)
```

## Architecture

### Design Principle: Let the Platform Handle Lifecycle

Process management (PID files, daemonization, signal handling, log rotation,
restart policies) is **not** the application's job.  These are infrastructure
concerns handled far better by the deployment platform:

| Concern | Docker | systemd | Kubernetes |
|---------|--------|---------|------------|
| Background | `docker run -d` | `Type=simple` | Pod spec |
| Restart | `restart: always` | `Restart=always` | `restartPolicy` |
| Logs | `docker logs` | `journalctl -u amcp` | `kubectl logs` |
| Health | `HEALTHCHECK` | `WatchdogSec=` | liveness probe |
| Resource limits | `--memory`, `--cpus` | `MemoryMax=` | resource requests |

AMCP therefore provides **application-level** background services that embed
into `amcp serve`, and leaves everything else to Docker / systemd.

### High-Level Design

```
┌──────────────────────────────────────────────────────────────┐
│  amcp serve  (FastAPI + Uvicorn)                             │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ BackgroundServices  (started in FastAPI lifespan)       │ │
│  │                                                         │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │ │
│  │  │  Heartbeat   │  │  Scheduler   │  │  Event        │ │ │
│  │  │  Monitor     │  │  (Cron)      │  │  Reactor      │ │ │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬────────┘ │ │
│  │         │                 │                  │          │ │
│  │         └─────────┬───────┴──────────────────┘          │ │
│  │                   │                                     │ │
│  │           ┌───────▼────────┐                            │ │
│  │           │  Task Runner   │                            │ │
│  │           │  (Agent Pool)  │                            │ │
│  │           └────────────────┘                            │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  HTTP API · WebSocket · Telegram · /api/v1/health            │
└──────────────────────────────────────────────────────────────┘
         ↑                          ↑
    Docker / systemd            config.toml
```

### Component Breakdown

```
src/amcp/
├── daemon/                    # "daemon" is now a misnomer — kept for compat
│   ├── __init__.py            # Exports BackgroundServices
│   ├── config.py              # DaemonConfig, HeartbeatConfig, SchedulerConfig, …
│   ├── daemon.py              # BackgroundServices: lightweight orchestrator
│   ├── heartbeat.py           # HeartbeatMonitor: periodic health checks
│   ├── scheduler.py           # CronScheduler: cron-style task scheduling
│   ├── reactor.py             # EventReactor: webhook/event-driven triggers
│   ├── task_runner.py         # TaskRunner: managed agent execution pool
│   └── jobs/
│       ├── __init__.py
│       ├── cleanup.py         # Session / memory cleanup
│       └── custom.py          # User-defined custom jobs
├── server/
│   └── app.py                 # lifespan() starts/stops BackgroundServices
deploy/
├── amcp.service               # systemd unit file
├── docker-compose.yml         # Docker Compose example
Dockerfile                     # Multi-stage build with HEALTHCHECK
```

## Configuration

### Config File (`~/.config/amcp/config.toml`)

```toml
[daemon]
enabled = true

[daemon.heartbeat]
enabled = true
interval = 60              # Heartbeat interval in seconds
unhealthy_threshold = 3    # Failures before alerting
check_memory = true
check_disk = true
max_memory_mb = 512

[daemon.scheduler]
enabled = true
timezone = "Asia/Shanghai"
max_concurrent_jobs = 3
job_timeout = 300

# Define cron jobs
[[daemon.scheduler.jobs]]
name = "ci-check"
schedule = "*/15 * * * *"
command = "Check CI status for all open PRs and report any failures"
skill = "gh-ci-analyzer"
enabled = true
notify = true

[[daemon.scheduler.jobs]]
name = "pr-review"
schedule = "0 */2 * * *"
command = "Review any new PRs that haven't been reviewed yet"
skill = "gh-code-review"
enabled = true
notify = true

[[daemon.scheduler.jobs]]
name = "memory-cleanup"
schedule = "0 4 * * *"
command = "Clean up old history entries and compact memory"
enabled = true
notify = false

[daemon.reactor]
enabled = false
listen_port = 4097
github_webhook_secret = ""
```

> **Note:** There are no `pid_file`, `log_file`, or `log_level` fields —
> those are handled by Docker / systemd.

## Core Components

### BackgroundServices

The lightweight orchestrator that replaces the old `AMCPDaemon`:

```python
class BackgroundServices:
    """Non-blocking orchestrator for AMCP background services."""

    async def start(self) -> None:
        """Start all enabled services (spawns background asyncio tasks)."""
        self.task_runner = TaskRunner(...)
        if config.heartbeat.enabled:
            asyncio.create_task(self.heartbeat.start())
        if config.scheduler.enabled:
            asyncio.create_task(self.scheduler.start())
        if config.reactor.enabled:
            asyncio.create_task(self.reactor.start())

    async def stop(self) -> None:
        """Gracefully stop all components."""
        ...

    def get_status(self) -> dict:
        """Return a summary of service status (for /health)."""
        ...
```

### HeartbeatMonitor

Periodic health checks emitting events via the Event Bus:

```python
@dataclass
class HealthStatus:
    healthy: bool
    uptime_seconds: float
    memory_usage_mb: float
    disk_free_gb: float
    active_jobs: int
    checks: dict[str, bool]
    error_details: dict[str, str]

class HeartbeatMonitor:
    async def check_health(self) -> HealthStatus: ...
    async def start(self) -> None:   # loop: check every N seconds
    async def stop(self) -> None:
```

Events emitted:
- `EventType.HEARTBEAT` — regular heartbeat
- `EventType.HEALTH_CHECK_FAILED` — a check failed
- `EventType.DAEMON_RECOVERED` — recovered from unhealthy state

### CronScheduler

Standard 5-field cron expressions plus shortcuts:

| Shortcut | Equivalent | Description |
|----------|------------|-------------|
| `@hourly` | `0 * * * *` | Every hour |
| `@daily` | `0 0 * * *` | Every day at midnight |
| `@weekly` | `0 0 * * 0` | Every Sunday at midnight |
| `@every 5m` | `*/5 * * * *` | Every 5 minutes |
| `@every 2h` | `0 */2 * * *` | Every 2 hours |

```python
class CronScheduler:
    async def start(self) -> None:      # main scheduler loop
    async def stop(self) -> None:
    def add_job(self, job) -> None:
    def remove_job(self, name) -> bool:
    def enable_job(self, name) -> None:
    def disable_job(self, name) -> None:
    def load_jobs_from_config(self) -> None:
```

### EventReactor

Webhook listener that maps events to agent commands:

```python
class EventReactor:
    async def start(self) -> None:  # starts asyncio TCP server
    async def stop(self) -> None:
    def add_rule(self, rule: ReactionRule) -> None:
    def _verify_signature(self, body, signature) -> bool:  # HMAC-SHA256
```

Default rules: `github.push` → run CI; `github.pull_request.opened` → review PR.

### TaskRunner

Managed agent execution pool with semaphore-based concurrency control:

```python
class TaskRunner:
    async def submit(self, command, *, skill=None, ...) -> str:  # returns task_id
    async def cancel(self, task_id) -> bool:
    async def cancel_all(self) -> None:
```

## CLI Commands

### Server (with background services)

```bash
# Start server — background services auto-start from config
amcp serve

# Explicitly enable scheduler / reactor via CLI flags
amcp serve --scheduler --reactor
amcp serve --host 0.0.0.0 --port 8080

# Check background services configuration
amcp daemon status
```

### Cron Job Management

```bash
# List scheduled jobs
amcp cron list

# Add a new job
amcp cron add "check-deps" \
    --schedule "0 8 * * 1" \
    --command "Check for outdated dependencies" \
    --notify

# Run a job immediately (outside the server)
amcp cron run ci-check

# Enable / disable
amcp cron enable pr-review
amcp cron disable memory-cleanup
```

## Deployment

### Docker

```bash
# Build
docker build -t amcp .

# Run
docker run -d -p 4096:4096 \
    -v ./config.toml:/root/.config/amcp/config.toml:ro \
    amcp serve --host 0.0.0.0

# With Docker Compose
cd deploy && docker compose up -d
```

The Dockerfile includes:
- `HEALTHCHECK` that pings `/api/v1/health`
- `ENTRYPOINT ["amcp"]` / `CMD ["serve", "--host", "0.0.0.0"]`
- `PYTHONUNBUFFERED=1` for real-time logging

### systemd

```bash
# Install service
sudo cp deploy/amcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now amcp

# Logs
journalctl -u amcp -f

# Status
systemctl status amcp
```

The unit file includes:
- `Restart=always` with `RestartSec=5`
- Security hardening (`NoNewPrivileges`, `ProtectSystem=strict`)
- `StandardOutput=journal` for journald integration

## Integration with Other Phases

### + Telegram (Phase 7)

Cron job results with `notify = true` are sent via Telegram:
```toml
[[daemon.scheduler.jobs]]
name = "ci-check"
notify = true    # → Sends Telegram notification
```

### + Memory

All cron job results are logged to memory with tags:
```python
mem.append_history(
    f"[Cron:{job.name}] {result}",
    tags=["cron", job.name],
)
```

### + Skills

Jobs can activate skills before execution:
```toml
[[daemon.scheduler.jobs]]
name = "pr-review"
skill = "gh-code-review"    # Skill activated automatically
command = "Review new PRs"
```

### + Server (Phase 5)

BackgroundServices are embedded in the FastAPI server lifespan, so
`amcp serve` is a single process that handles HTTP API, WebSocket,
Telegram, scheduler, reactor, and health checks.

## Security

1. **Job Isolation**: Each job runs in its own agent session
2. **Timeout Enforcement**: Jobs are killed after the configured timeout
3. **Concurrency Control**: Semaphore-based limit on concurrent jobs
4. **Resource Monitoring**: Memory and disk usage health checks
5. **Audit Trail**: All executions logged to memory history
6. **Webhook Auth**: GitHub webhook HMAC-SHA256 signature verification

## Testing

28 tests in `tests/test_daemon.py` covering:

- `TestDaemonConfig` — defaults, heartbeat, scheduler, reactor configs
- `TestCronJob` — from_config, schedule expansion (@hourly, @every 5m, …)
- `TestCronScheduler` — add/remove/enable/disable jobs, load from config
- `TestHeartbeatMonitor` — health checks, memory limits, running state
- `TestTaskRunner` — initial state, submit and await tasks
- `TestBackgroundServices` — initial state, get_status, start/stop lifecycle
- `TestEventReactor` — default rules, custom rules, signature verification
- `TestDaemonEventTypes` — event type enum values
- `TestDaemonConfigRoundtrip` — decode ↔ encode consistency
- `TestCleanupJobs` / `TestCustomJobs` — built-in job helpers

## Dependencies

```toml
[project.optional-dependencies]
daemon = [
    "croniter>=2.0",        # Cron expression parsing
    "psutil>=5.9",          # System resource monitoring (optional)
]
```
