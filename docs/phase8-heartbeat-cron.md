# AMCP Phase 8: Heartbeat + Cron (Autonomous Operation)

Enables AMCP to operate autonomously with scheduled tasks, periodic health checks, and event-driven actions — transforming it from a reactive assistant into a proactive agent.

## Motivation

Currently, AMCP only acts when a user sends a message. With Heartbeat + Cron, the agent can:

- **Run scheduled tasks**: Automatically check CI, review new PRs, monitor systems
- **Self-maintain**: Clean up old sessions, compact memory, update skills
- **React to events**: Trigger actions based on GitHub webhooks, file changes, or custom events
- **Stay alive**: Heartbeat mechanism ensures the agent is healthy and responsive
- **Evolve independently**: Combined with Skill Creator + Memory, enables a self-improving agent loop

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

### High-Level Design

```
┌────────────────────────────────────────────────────────────┐
│                     AMCP Daemon                             │
│                                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │   Heartbeat  │  │  Scheduler   │  │  Event Reactor   │ │
│  │   Monitor    │  │  (Cron)      │  │  (Webhooks)      │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────────┘ │
│         │                 │                  │             │
│         └─────────┬───────┴──────────────────┘             │
│                   │                                        │
│           ┌───────▼────────┐                               │
│           │  Task Runner   │                               │
│           │  (Agent Pool)  │                               │
│           └───────┬────────┘                               │
│                   │                                        │
│    ┌──────────────┼──────────────────┐                     │
│    │              │                  │                     │
│    ▼              ▼                  ▼                     │
│  Agent          Memory           Telegram                  │
│  (Core)         (Logging)        (Notifications)           │
└────────────────────────────────────────────────────────────┘
```

### Component Breakdown

```
src/amcp/
├── daemon/
│   ├── __init__.py
│   ├── daemon.py          # AMCPDaemon: main daemon lifecycle
│   ├── heartbeat.py       # HeartbeatMonitor: health checks
│   ├── scheduler.py       # CronScheduler: cron-style task scheduling
│   ├── reactor.py         # EventReactor: webhook/event-driven triggers
│   ├── task_runner.py     # TaskRunner: managed agent execution pool
│   └── jobs/
│       ├── __init__.py
│       ├── ci_monitor.py  # CI status monitoring job
│       ├── pr_review.py   # Automatic PR review job
│       ├── cleanup.py     # Session/memory cleanup job
│       └── custom.py      # User-defined custom jobs
```

## Configuration

### Config File (`~/.config/amcp/config.toml`)

```toml
[daemon]
enabled = true
pid_file = "~/.config/amcp/amcp.pid"
log_file = "~/.config/amcp/logs/daemon.log"
log_level = "info"

[daemon.heartbeat]
enabled = true
interval = 60              # Heartbeat interval in seconds
unhealthy_threshold = 3    # Failures before restart
check_memory = true        # Monitor memory usage
check_disk = true          # Monitor disk space
max_memory_mb = 512        # Memory usage limit

[daemon.scheduler]
enabled = true
timezone = "Asia/Shanghai"
max_concurrent_jobs = 3    # Max concurrent cron jobs
job_timeout = 300          # Default job timeout (seconds)

# Define cron jobs
[[daemon.scheduler.jobs]]
name = "ci-check"
schedule = "*/15 * * * *"    # Every 15 minutes
command = "Check CI status for all open PRs and report any failures"
skill = "gh-ci-analyzer"     # Optional: activate a skill for this job
enabled = true
notify = true                # Send notification on completion

[[daemon.scheduler.jobs]]
name = "pr-review"
schedule = "0 */2 * * *"     # Every 2 hours
command = "Review any new PRs that haven't been reviewed yet"
skill = "gh-code-review"
enabled = true
notify = true

[[daemon.scheduler.jobs]]
name = "memory-cleanup"
schedule = "0 4 * * *"       # Daily at 4 AM
command = "Clean up old history entries and compact memory"
enabled = true
notify = false

[[daemon.scheduler.jobs]]
name = "daily-summary"
schedule = "0 18 * * 1-5"    # Weekdays at 6 PM
command = "Generate a summary of today's activities and accomplishments"
enabled = true
notify = true

[daemon.reactor]
enabled = false                # Enable webhook-based triggers
listen_port = 4097            # Webhook listener port
github_webhook_secret = ""    # GitHub webhook secret
```

## Heartbeat Monitor

The heartbeat ensures the daemon and its agents remain healthy.

### Health Checks

```python
@dataclass
class HealthStatus:
    """Daemon health status."""
    healthy: bool
    uptime_seconds: float
    memory_usage_mb: float
    active_jobs: int
    active_sessions: int
    last_heartbeat: datetime
    checks: dict[str, bool]    # Individual check results

class HeartbeatMonitor:
    """Monitor daemon health."""

    async def check_health(self) -> HealthStatus:
        """Run all health checks."""
        checks = {
            "agent_responsive": await self._check_agent(),
            "memory_available": self._check_memory(),
            "disk_space": self._check_disk(),
            "api_reachable": await self._check_api(),
        }
        return HealthStatus(
            healthy=all(checks.values()),
            checks=checks,
            ...
        )

    async def _on_unhealthy(self, status: HealthStatus):
        """Handle unhealthy status."""
        # 1. Log the issue
        logger.warning(f"Unhealthy: {status.checks}")
        # 2. Attempt self-recovery
        if not status.checks["agent_responsive"]:
            await self._restart_agent()
        # 3. Notify user (via Telegram if available)
        await self._send_alert(status)
```

### Heartbeat Events

```python
# Heartbeat emits events via Event Bus
EventType.HEARTBEAT           # Regular heartbeat
EventType.HEALTH_CHECK_FAILED # A health check failed
EventType.DAEMON_RECOVERED    # Daemon recovered from unhealthy state
```

## Cron Scheduler

### Cron Expression Support

Standard 5-field cron expressions:

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, 0=Sunday)
│ │ │ │ │
* * * * *
```

Plus shortcuts:
| Shortcut | Equivalent | Description |
|----------|------------|-------------|
| `@hourly` | `0 * * * *` | Every hour |
| `@daily` | `0 0 * * *` | Every day at midnight |
| `@weekly` | `0 0 * * 0` | Every Sunday at midnight |
| `@every 5m` | `*/5 * * * *` | Every 5 minutes |
| `@every 2h` | `0 */2 * * *` | Every 2 hours |

### Job Definition

```python
@dataclass
class CronJob:
    """A scheduled job."""
    name: str
    schedule: str              # Cron expression
    command: str               # Prompt to send to agent
    skill: str | None = None   # Optional skill to activate
    enabled: bool = True
    notify: bool = True        # Notify on completion
    timeout: int = 300         # Timeout in seconds
    work_dir: str | None = None
    tags: list[str] = field(default_factory=list)

    # Runtime state
    last_run: datetime | None = None
    last_result: str | None = None
    last_status: str = "idle"  # idle, running, success, failed
    run_count: int = 0
    failure_count: int = 0
```

### Scheduler Implementation

```python
class CronScheduler:
    """Cron-style task scheduler."""

    def __init__(self, agent_factory, config):
        self.jobs: dict[str, CronJob] = {}
        self.agent_factory = agent_factory
        self._running = False

    async def start(self):
        """Start the scheduler loop."""
        self._running = True
        while self._running:
            now = datetime.now(self.timezone)
            for job in self.jobs.values():
                if job.enabled and self._should_run(job, now):
                    asyncio.create_task(self._execute_job(job))
            await asyncio.sleep(30)  # Check every 30 seconds

    async def _execute_job(self, job: CronJob):
        """Execute a scheduled job."""
        job.last_run = datetime.now()
        job.last_status = "running"

        try:
            agent = self.agent_factory()
            if job.skill:
                agent.activate_skill(job.skill)

            result = await asyncio.wait_for(
                agent.run(job.command, work_dir=job.work_dir),
                timeout=job.timeout,
            )

            job.last_result = result
            job.last_status = "success"
            job.run_count += 1

            # Log to memory
            memory_mgr.append_history(
                content=f"[Cron:{job.name}] {result[:500]}",
                tags=["cron", job.name, *job.tags],
            )

            # Notify if configured
            if job.notify:
                await self._notify(job, result)

        except asyncio.TimeoutError:
            job.last_status = "failed"
            job.failure_count += 1
            logger.error(f"Job {job.name} timed out")

        except Exception as e:
            job.last_status = "failed"
            job.failure_count += 1
            logger.error(f"Job {job.name} failed: {e}")
```

## CLI Integration

### Daemon Commands

```bash
# Start the daemon
amcp daemon start
amcp daemon start --foreground          # Run in foreground (for debugging)
amcp daemon start --config custom.toml  # Custom config

# Stop the daemon
amcp daemon stop

# Check status
amcp daemon status

# View logs
amcp daemon logs
amcp daemon logs --follow               # Tail logs
amcp daemon logs --lines 50             # Last 50 lines
```

### Job Management

```bash
# List scheduled jobs
amcp cron list

# Output:
#   NAME              SCHEDULE        NEXT RUN      LAST STATUS  RUNS
#   ci-check          */15 * * * *    in 3m         ✅ success    42
#   pr-review         0 */2 * * *     in 1h 23m     ✅ success    12
#   memory-cleanup    0 4 * * *       in 8h 15m     ✅ success     3
#   daily-summary     0 18 * * 1-5    tomorrow      ⏳ idle        0

# Add a new job
amcp cron add "check-deps" \
    --schedule "0 8 * * 1" \
    --command "Check for outdated dependencies and report" \
    --notify

# Run a job immediately
amcp cron run ci-check

# Enable/disable a job
amcp cron enable pr-review
amcp cron disable memory-cleanup

# View job history
amcp cron history ci-check
```

## Event Reactor (Webhook Triggers)

For event-driven operation beyond scheduled tasks:

```python
class EventReactor:
    """React to external events like GitHub webhooks."""

    def __init__(self):
        self.triggers: dict[str, list[ReactionRule]] = {}

    def on_github_push(self, payload: dict):
        """React to GitHub push events."""
        branch = payload["ref"].split("/")[-1]
        if branch == "main":
            self.schedule_immediate(
                "CI was triggered on main branch. "
                "Monitor the run and report any failures."
            )

    def on_github_pr(self, payload: dict):
        """React to GitHub PR events."""
        action = payload["action"]
        if action == "opened":
            pr_number = payload["number"]
            self.schedule_immediate(
                f"A new PR #{pr_number} was opened. "
                f"Review it using the gh-code-review skill."
            )
```

## Process Management

### Daemon Lifecycle

```python
class AMCPDaemon:
    """Main daemon process."""

    async def start(self):
        """Start all daemon components."""
        # 1. Write PID file
        self._write_pid()

        # 2. Start heartbeat monitor
        self.heartbeat = HeartbeatMonitor(config)
        asyncio.create_task(self.heartbeat.start())

        # 3. Start cron scheduler
        self.scheduler = CronScheduler(self.agent_factory, config)
        asyncio.create_task(self.scheduler.start())

        # 4. Start event reactor (if enabled)
        if config.reactor.enabled:
            self.reactor = EventReactor(config)
            asyncio.create_task(self.reactor.start())

        # 5. Log startup
        logger.info("AMCP Daemon started")
        memory_mgr.append_history(
            "AMCP Daemon started",
            tags=["daemon", "lifecycle"],
        )

    async def stop(self):
        """Gracefully stop all components."""
        self._running = False
        await self.scheduler.stop()
        await self.heartbeat.stop()
        if self.reactor:
            await self.reactor.stop()
        self._remove_pid()
        logger.info("AMCP Daemon stopped")

    def _write_pid(self):
        """Write PID file for process management."""
        pid_file = Path(self.config.pid_file).expanduser()
        pid_file.write_text(str(os.getpid()))

    def _remove_pid(self):
        """Remove PID file on shutdown."""
        pid_file = Path(self.config.pid_file).expanduser()
        pid_file.unlink(missing_ok=True)
```

### Signal Handling

```python
import signal

def setup_signal_handlers(daemon: AMCPDaemon):
    """Handle OS signals for graceful shutdown."""
    loop = asyncio.get_event_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(daemon.stop()),
        )
```

## Integration with Other Phases

### + Telegram (Phase 7)

```python
# Cron job results are automatically sent via Telegram
[[daemon.scheduler.jobs]]
name = "ci-check"
schedule = "*/15 * * * *"
command = "Check CI status for all open PRs"
notify = true    # → Sends Telegram notification
```

### + Memory (Already Implemented)

```python
# All cron job results are logged to memory
memory_mgr.append_history(
    content=f"[Cron:{job.name}] {result}",
    tags=["cron", job.name],
)
```

### + Skills (Already Implemented)

```python
# Jobs can activate skills before execution
[[daemon.scheduler.jobs]]
name = "pr-review"
skill = "gh-code-review"    # Skill activated automatically
command = "Review new PRs"
```

## Dependencies

```toml
[project.optional-dependencies]
daemon = [
    "croniter>=2.0",        # Cron expression parsing
    "psutil>=5.9",          # System resource monitoring
]
```

## Security Considerations

1. **PID File**: Prevents multiple daemon instances
2. **Job Isolation**: Each job runs in its own agent session
3. **Timeout Enforcement**: Jobs are killed after timeout
4. **Resource Limits**: Memory and CPU usage monitoring
5. **Audit Trail**: All job executions logged to memory history
6. **Webhook Auth**: GitHub webhook signature verification

## Testing Strategy

```python
# tests/test_daemon.py
class TestCronScheduler:
    def test_cron_expression_parsing(self): ...
    def test_job_execution(self): ...
    def test_job_timeout(self): ...
    def test_concurrent_job_limit(self): ...

class TestHeartbeatMonitor:
    def test_healthy_status(self): ...
    def test_unhealthy_detection(self): ...
    def test_auto_recovery(self): ...

class TestAMCPDaemon:
    def test_start_stop(self): ...
    def test_signal_handling(self): ...
    def test_pid_file(self): ...
```

## Version

Heartbeat + Cron is planned for **AMCP v0.11.0**.
