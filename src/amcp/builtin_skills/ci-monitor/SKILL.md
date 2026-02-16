---
name: ci-monitor
description: Monitor CI/CD pipeline status for open pull requests. Checks GitHub Actions runs and reports failures.
triggers:
  - schedule: "*/15 * * * *"
    command: "Check CI status for all open PRs in this repository. Report any failing or pending checks. If a PR has been failing for more than 1 hour, highlight it as urgent."
    notify: true
    timeout: 120
  - event: github.push
    command: "A push was made to the repository. Check if CI was triggered and monitor the run status. Report any failures."
    notify: true
---

# CI Monitor

Automatically monitor CI/CD pipeline status and report issues.

## Monitoring Procedure

1. Run `gh pr list --state open --json number,title,headRefName,statusCheckRollup` to get all open PRs
2. For each PR, check the status of CI checks
3. Identify:
   - ❌ **Failed** checks — report immediately
   - ⏳ **Pending** checks running for >30 minutes — flag as slow
   - ✅ **Passed** checks — note in summary
4. If `notify: true`, format a concise status report

## Tools to Use

- `gh pr list` — list open PRs with status
- `gh pr checks <number>` — detailed check status for a PR
- `gh run list` — recent workflow runs
- `gh run view <id>` — details of a specific run

## Report Format

```
CI Status Report:
✅ PR #42 "Add feature X" — all checks passed
❌ PR #43 "Fix bug Y" — lint check failed (2h ago)
⏳ PR #44 "Update deps" — tests running (15m)
```
