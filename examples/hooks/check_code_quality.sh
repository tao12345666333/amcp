#!/bin/bash
# Example hook script: Run code quality checks after file writes
#
# This PostToolUse hook runs linting and formatting checks on newly written files.
#
# Input: JSON via stdin
# Output: JSON to stdout (optional) or exit codes:
#   0 = success (stdout is processed)
#   2 = blocking error (stderr is used as error message)
#   other = non-blocking error (logged, execution continues)

set -e

# Read input
INPUT=$(cat)

# Parse tool info
TOOL_NAME=$(echo "$INPUT" | python3 -c "import json, sys; print(json.load(sys.stdin).get('tool_name', ''))")
TOOL_INPUT=$(echo "$INPUT" | python3 -c "import json, sys; print(json.dumps(json.load(sys.stdin).get('tool_input', {})))")

# Only process write_file tool
if [ "$TOOL_NAME" != "write_file" ]; then
    exit 0
fi

# Get the file path
FILE_PATH=$(echo "$TOOL_INPUT" | python3 -c "import json, sys; print(json.load(sys.stdin).get('path', ''))")

# Check if it's a Python file
if [[ "$FILE_PATH" == *.py ]]; then
    # Check if ruff is available
    if command -v ruff &> /dev/null; then
        # Run ruff check
        LINT_OUTPUT=$(ruff check "$FILE_PATH" 2>&1 || true)
        
        if [ -n "$LINT_OUTPUT" ]; then
            # Return feedback about lint issues
            echo "{\"feedback\": \"Lint issues found:\\n$LINT_OUTPUT\"}"
        fi
    fi
fi

# Success
exit 0
