# AMCP Phase 8 (Simplified): External Orchestrator + Skill Automation

This document replaces the previous "big in-process daemon" design with a
simpler **Telegram-first + skill-driven** model.

## Why simplify

After reviewing `src/amcp/daemon/`, the current design is functionally rich but
overly coupled:

1. **Too many responsibilities in one process**
   - scheduler, heartbeat, webhook reactor, task runner, skill watcher
2. **Execution path duplication**
   - `CronScheduler` runs agents directly
   - `TaskRunner` is a second execution abstraction
3. **Infra concerns leak into app concerns**
   - health/restart/reliability are better handled by Docker/systemd/K8s
4. **Webhook listener in app runtime adds complexity/risk**
   - custom HTTP parsing, signature verification, extra attack surface
5. **Direction mismatch with current product path**
   - AMCP is moving to **Telegram as the main interaction surface**
   - new automation behavior can be expressed as **skills**

## Design principles (new)

1. **Platform manages process lifecycle**
   - restart, supervision, logs, health probes: Docker/systemd/K8s
2. **AMCP focuses on execution intelligence**
   - agent runtime, skills, memory, Telegram interaction
3. **Automation is trigger + skill, not daemon subsystem sprawl**
4. **Prefer stateless/job-style invocation for background work**
5. **Telegram is the default human interface for proactive output**

## New target architecture

```text
┌───────────────────────────────────────────────────────┐
│ External Orchestrators                               │
│ - systemd timer / cron / K8s CronJob / CI workflow   │
│ - webhook gateway (GitHub Actions, n8n, etc.)        │
└──────────────────────┬────────────────────────────────┘
                       │ invoke
                       ▼
┌───────────────────────────────────────────────────────┐
│ AMCP runtime                                           │
│                                                       │
│ 1) Long-lived (optional):                             │
│    - amcp serve (API/WebSocket)                       │
│    - amcp telegram start                              │
│    - skill auto-discovery / hot reload               │
│                                                       │
│ 2) One-shot jobs (preferred for automation):          │
│    - amcp --once "<command>"                          │
│    - amcp cron run <job-name>                        │
│                                                       │
│ 3) Result channel: Telegram notifications             │
└───────────────────────────────────────────────────────┘
```

## What stays vs what is deprecated

### Keep

- Skill discovery / activation / hot reload
- Telegram bot integration
- `amcp serve` for API/WebSocket sessions
- `amcp --once` for stateless task execution
- `amcp cron run` as a simple named-job executor

### Removed

- In-process **EventReactor** HTTP webhook server
- In-process **HeartbeatMonitor** as reliability strategy
- In-process **TaskRunner** pool abstraction for background orchestration

> These components are removed from the runtime path.

## Telegram-first operating model

### Human-driven

- User interacts via Telegram private/group chat
- Bot maps intent -> agent execution -> response back to Telegram

### Automated

- External scheduler/event system triggers AMCP job
- Job executes with skills
- Outcome sent to Telegram channel/group/user

## Skill-centric automation model

Automation logic should live in skills (prompt + scripts + references), not in
hard-coded daemon subsystems.

Example skill frontmatter (existing style):

```yaml
---
name: ci-checker
description: Check repo CI and report failures
triggers:
  - schedule: "*/15 * * * *"
    command: "Check CI status for all open PRs and summarize failures"
    notify: true
---
```

Interpretation in simplified architecture:

- `triggers` are **declarative intent**
- actual scheduling is performed by external orchestrators
- AMCP executes the command and handles skill context + reporting

## Deployment recommendations

## 1) systemd (recommended for self-hosted)

- `amcp-telegram.service`: keep bot online
- `amcp-serve.service` (optional): API server
- `amcp-job-*.timer`: periodic jobs invoking one-shot AMCP commands

Example timer action:

```bash
amcp cron run ci-check
```

or directly:

```bash
amcp --once "Check CI status for all open PRs and summarize failures"
```

## 2) Docker/K8s

- Long-lived deployment for Telegram/API
- CronJob resources for scheduled tasks
- Standard health probes against `/api/v1/health`

## Configuration direction

Move toward a lighter model where config stores **job definitions**, not daemon
subsystem internals.

Suggested target shape (future):

```toml
[automation]
enabled = true
default_timeout = 300

[[automation.jobs]]
name = "ci-check"
command = "Check CI status for all open PRs and summarize failures"
skill = "ci-checker"
notify = true
```

Scheduler-specific timing should live in systemd/cron/K8s rather than AMCP core.

## Implementation status

- `src/amcp/daemon/` removed
- daemon-related config and CLI flags removed
- `amcp cron` now uses `[automation.jobs]` only
- `amcp serve` keeps API/WebSocket + skill hot reload only

## Decision summary

For AMCP’s current trajectory, **a heavy internal daemon is not necessary as the
primary architecture**.

The recommended architecture is:

- **Telegram-first interaction**
- **Skill-driven automation logic**
- **External orchestrator-managed scheduling and lifecycle**
- **AMCP as execution engine, not process supervisor**

