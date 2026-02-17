---
name: session-cleanup
description: Backup old AMCP sessions by renaming with execution date, then clean and compact sessions and memory.
triggers:
  - schedule: "0 4 * * *"
    command: "Backup old session files by renaming with execution date, then clean and compact sessions and memory. Report what was backed up and cleaned."
    notify: false
    timeout: 180
---

# Session Cleanup

Backup old AMCP sessions by renaming with execution date, then clean and compact sessions and memory to keep the system efficient.

## What to Clean

1. **Session files backup**: Rename session JSON files in `~/.config/amcp/sessions/` that haven't been modified in 30+ days to `YYYY-MM-DD_<original_name>.json.bak`
2. **Active sessions keep**: Keep the most recent 10 session files (by modification time) as active
3. **Memory compaction**: Compact `~/.config/amcp/memory/HISTORY.md` to keep only the last 50 entries

## Procedure

### Step 1: Backup Old Sessions

1. List all `.json` files in `~/.config/amcp/sessions/` directory
2. Get modification time of each file
3. Sort by modification time (oldest first)
4. Keep the 10 most recent files as active
5. For files older than 30 days (or beyond the 10 most recent):
   - Rename to `YYYY-MM-DD_<original_name>.json.bak` where YYYY-MM-DD is the current execution date
   - Move to a `backups/` subdirectory within sessions folder

### Step 2: Clean Backup Files

1. Remove `.bak` backup files older than 90 days to free space
2. Report: "Backed up N session files, cleaned M old backups, freed X MB"

### Step 3: Compact Memory

1. Read `~/.config/amcp/memory/HISTORY.md`
2. Count the number of entries (each `-` bullet is an entry)
3. If more than 50 entries, keep only the last 50 entries
4. Add a summary entry at the top: "Compacted from X entries to 50 entries on YYYY-MM-DD"

## Safety

- Never delete the currently active session (most recent)
- Only delete `.json` and `.bak` files (not directories or other file types)
- Always create backups before any cleanup operation
- Log each operation for audit trail

## Example Output

```
Session Cleanup Report (2026-02-16):
- Active sessions kept: 10
- Sessions backed up: 15
- Old backups removed: 3
- Space freed: 45 MB
- Memory entries: compacted from 120 to 50
```
