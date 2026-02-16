---
name: session-cleanup
description: Clean up old AMCP sessions and compact memory. Removes session files older than 30 days and optimizes memory storage.
triggers:
  - schedule: "0 4 * * *"
    command: "Clean up old session files (older than 30 days) and compact memory history. Report how many files were cleaned and how much space was freed."
    notify: false
    timeout: 120
---

# Session Cleanup

Periodically clean up old AMCP sessions and compact memory to keep the system efficient.

## What to Clean

1. **Old session files**: Delete session JSON files in `~/.config/amcp/sessions/` that haven't been modified in 30+ days
2. **Memory compaction**: If memory history has grown large, summarize older entries

## Procedure

1. List files in `~/.config/amcp/sessions/` directory
2. Check modification time of each `.json` file
3. Delete files older than 30 days
4. Report: "Cleaned N session files, freed X MB"

## Safety

- Never delete the currently active session
- Only delete `.json` files (not directories or other file types)
- Log each deletion for audit trail
