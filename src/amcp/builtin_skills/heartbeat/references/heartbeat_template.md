# HEARTBEAT.md Reference

## Purpose

`HEARTBEAT.md` is a workspace-level task file that the heartbeat skill checks every 30 minutes.
Place it at the root of your workspace. The agent reads it, executes any tasks listed under
`## Active Tasks`, and moves completed items to `## Completed`.

## Template

```markdown
# Heartbeat Tasks

This file is checked every 30 minutes by your AMCP agent.
Add tasks below that you want the agent to work on periodically.

If this file has no tasks (only headers and comments), the agent will skip the heartbeat.

## Active Tasks

<!-- Add your periodic tasks below this line -->


## Completed

<!-- Completed tasks are moved here automatically -->
```

## Example Active Tasks

```markdown
## Active Tasks

- Check CI status for all open PRs and report any failures
- Review any new PRs that haven't been reviewed yet
- Check for outdated dependencies and create a summary
- Run ruff check on src/ and fix any issues
```
