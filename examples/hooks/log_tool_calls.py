#!/usr/bin/env python3
"""
Example hook script: Log all tool calls.

This script is called for every tool execution and logs the tool call
to a file for auditing purposes.

Input: JSON via stdin with the following structure:
{
    "session_id": "...",
    "hook_event_name": "PreToolUse",
    "cwd": "/path/to/project",
    "tool_name": "read_file",
    "tool_input": {"path": "..."},
    "tool_use_id": "..."
}

Output: JSON to stdout (optional) with the following structure:
{
    "continue": true,  // Whether to continue execution
    "feedback": "...",  // Optional feedback message
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",  // "allow", "deny", or "ask"
        "permissionDecisionReason": "...",
        "updatedInput": {...}  // Optional modified input
    }
}
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def main():
    # Read input from stdin
    input_data = json.load(sys.stdin)
    
    # Log to file
    log_file = Path("/tmp/amcp_tool_calls.log")
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": input_data.get("session_id"),
        "tool_name": input_data.get("tool_name"),
        "tool_input": input_data.get("tool_input"),
    }
    
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")
    
    # Return success (exit code 0 = success)
    # No output means continue with default behavior
    sys.exit(0)


if __name__ == "__main__":
    main()
