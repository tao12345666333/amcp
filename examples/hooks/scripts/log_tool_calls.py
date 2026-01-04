#!/usr/bin/env python3
"""
Tool Call Logger Hook Script

Logs all tool calls for audit and analysis purposes.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

def log_tool_call(hook_data: dict):
    """Log tool call information."""
    log_dir = Path.home() / ".amcp" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"tool_calls_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "tool": hook_data.get("tool", "unknown"),
        "args": hook_data.get("args", {}),
        "result": hook_data.get("result", {}),
        "duration_ms": hook_data.get("duration_ms", 0),
        "success": hook_data.get("success", True),
        "error": hook_data.get("error", None)
    }
    
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

def main():
    """Main hook function."""
    try:
        # Read hook input from stdin
        hook_input = json.load(sys.stdin)
        
        # Log the tool call
        log_tool_call(hook_input)
        
        print(f"✅ Logged tool call: {hook_input.get('tool', 'unknown')}")
        sys.exit(0)
        
    except Exception as e:
        print(f"Error logging tool call: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()