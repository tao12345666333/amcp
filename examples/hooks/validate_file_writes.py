#!/usr/bin/env python3
"""
Example hook script: Validate and potentially block dangerous file writes.

This PreToolUse hook checks file writes and can:
- Allow safe writes
- Deny writes to sensitive files
- Modify the file path or content

Input: JSON via stdin (see log_tool_calls.py for format)
Output: JSON decision to stdout
"""

import json
import sys
from pathlib import Path

# List of sensitive patterns that should be blocked
BLOCKED_PATTERNS = [
    ".env",
    ".secrets",
    "credentials",
    "password",
    ".ssh/",
    ".gnupg/",
]

# List of patterns that require user confirmation
ASK_PATTERNS = [
    "config",
    ".github/",
    "Dockerfile",
]


def should_block(file_path: str) -> tuple[bool, str]:
    """Check if a file path should be blocked."""
    path_lower = file_path.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in path_lower:
            return True, f"Writing to '{file_path}' is blocked for security reasons (matches pattern: {pattern})"
    return False, ""


def should_ask(file_path: str) -> tuple[bool, str]:
    """Check if a file path requires user confirmation."""
    path_lower = file_path.lower()
    for pattern in ASK_PATTERNS:
        if pattern in path_lower:
            return True, f"Writing to '{file_path}' requires confirmation (matches pattern: {pattern})"
    return False, ""


def main():
    # Read input from stdin
    input_data = json.load(sys.stdin)
    
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    
    # Only process write_file and edit_file tools
    if tool_name not in ("write_file", "edit_file"):
        # Allow other tools to pass through
        sys.exit(0)
    
    file_path = tool_input.get("path", tool_input.get("file_path", ""))
    
    # Check if should block
    blocked, block_reason = should_block(file_path)
    if blocked:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": block_reason,
            }
        }
        print(json.dumps(output))
        sys.exit(0)
    
    # Check if should ask for confirmation
    ask, ask_reason = should_ask(file_path)
    if ask:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": ask_reason,
            }
        }
        print(json.dumps(output))
        sys.exit(0)
    
    # Allow the operation
    sys.exit(0)


if __name__ == "__main__":
    main()
