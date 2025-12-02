# Design Document

## Overview

This feature adds support for gracefully handling Ctrl+D (EOF signal) in the `amcp agent` interactive mode. Currently, users can only exit using explicit commands like 'exit', 'quit', or 'q'. Adding Ctrl+D support provides a more natural terminal experience consistent with standard CLI tools and REPL environments.

The implementation will catch the `EOFError` exception raised when users press Ctrl+D and perform the same cleanup and exit sequence as the existing exit commands.

## Architecture

The change is localized to the interactive loop in `src/amcp/cli.py`. The architecture follows the existing pattern:

1. **Input Layer**: The `console.input()` call in the interactive loop
2. **Exception Handling**: New `EOFError` catch block
3. **Exit Sequence**: Reuse existing goodbye message and cleanup logic

No new components or modules are required. The change integrates seamlessly with the existing conversation history persistence and session management.

## Components and Interfaces

### Modified Component: Interactive Loop (`src/amcp/cli.py`)

**Current Implementation:**
```python
while True:
    try:
        user_input = console.input("[bold]You:[/bold] ").strip()
        
        if user_input.lower() in ['exit', 'quit', 'q']:
            console.print("[green]Goodbye! 👋[/green]")
            break
        # ... rest of loop
    except KeyboardInterrupt:
        console.print("\\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
```

**Modified Implementation:**
The `EOFError` exception will be caught at the same level as `KeyboardInterrupt`, providing consistent exception handling for terminal signals.

### Interface Changes

No public API changes. The modification is internal to the CLI interactive loop. The behavior change is:

- **Before**: Ctrl+D causes an unhandled `EOFError`, potentially crashing or displaying an error
- **After**: Ctrl+D triggers graceful exit with goodbye message and proper cleanup

## Data Models

No data model changes required. The existing session management and conversation history structures remain unchanged.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: EOF signal triggers graceful exit
*For any* interactive session, when an EOF signal (Ctrl+D) is received, the system should exit the interactive loop and display a goodbye message.
**Validates: Requirements 1.1, 1.2**

### Property 2: Conversation history persists on EOF exit
*For any* interactive session with conversation history, when an EOF signal triggers exit, the conversation history should be saved before the program terminates.
**Validates: Requirements 1.3**

### Property 3: EOF exit performs same cleanup as explicit exit
*For any* interactive session, the cleanup operations performed when exiting via EOF signal should be equivalent to the cleanup operations performed when exiting via explicit 'exit' command.
**Validates: Requirements 1.4**

### Property 4: Backward compatibility maintained
*For any* existing exit command ('exit', 'quit', 'q'), the command should continue to function identically after EOF handling is added.
**Validates: Requirements 1.5**

## Error Handling

### EOFError Handling

The `EOFError` exception is raised by Python's `input()` function when it encounters an EOF signal:
- **Unix/Linux/macOS**: Ctrl+D
- **Windows**: Ctrl+Z followed by Enter

**Handling Strategy:**
1. Catch `EOFError` in the same try-except block as other exceptions
2. Print goodbye message using the same format as explicit exit commands
3. Break from the interactive loop
4. Allow normal program termination (which triggers existing cleanup via Agent's `_save_conversation_history()`)

### Edge Cases

1. **EOF on empty input**: Should exit gracefully (standard behavior)
2. **EOF mid-input**: Should exit gracefully, discarding partial input
3. **Multiple EOF signals**: First EOF should exit; subsequent signals are irrelevant
4. **EOF during agent processing**: Handled by existing `KeyboardInterrupt` logic (Ctrl+C), not EOF

## Testing Strategy

### Unit Tests

Unit tests will verify the core EOF handling logic:

1. **Test EOF triggers exit**: Simulate `EOFError` and verify the loop exits
2. **Test goodbye message displayed**: Verify correct message is printed on EOF
3. **Test backward compatibility**: Verify existing exit commands still work
4. **Test conversation history saved**: Verify `_save_conversation_history()` is called before exit

### Property-Based Tests

Property-based tests will verify the universal behaviors:

1. **Property 1 Test**: Generate random interactive sessions, inject EOF signal, verify graceful exit with goodbye message
2. **Property 2 Test**: Generate random sessions with conversation history, inject EOF, verify history is persisted
3. **Property 3 Test**: Compare cleanup operations between EOF exit and explicit exit command, verify equivalence
4. **Property 4 Test**: Generate random exit commands from the set {'exit', 'quit', 'q'}, verify all still function correctly

### Testing Framework

- **Unit Testing**: pytest
- **Property-Based Testing**: Hypothesis (Python PBT library)
- **Mocking**: unittest.mock for simulating user input and EOF signals

### Test Configuration

- Property-based tests will run a minimum of 100 iterations
- Tests will mock `console.input()` to simulate EOF without requiring actual terminal interaction
- Tests will verify both stdout output and internal state changes

## Implementation Notes

### Design Decisions

**Decision 1: Reuse existing exit logic**
- **Rationale**: The existing exit commands already handle cleanup correctly. By catching `EOFError` and breaking from the loop, we leverage the same cleanup path.
- **Alternative considered**: Implement separate cleanup function. Rejected due to code duplication and maintenance burden.

**Decision 2: Same goodbye message for all exit methods**
- **Rationale**: Consistency in user experience. Users should see the same friendly goodbye regardless of how they exit.
- **Alternative considered**: Different message for EOF. Rejected as it adds complexity without user benefit.

**Decision 3: Place EOFError handler alongside KeyboardInterrupt**
- **Rationale**: Both are terminal signal exceptions. Grouping them improves code readability and maintainability.
- **Alternative considered**: Separate try-except block. Rejected as it would duplicate exception handling structure.

### Minimal Change Principle

This design follows the principle of minimal change:
- Single exception handler addition
- No new functions or classes
- No changes to data structures
- No changes to existing exit logic
- Estimated change: ~4 lines of code

### Platform Compatibility

The implementation is platform-agnostic:
- Python's `EOFError` is raised consistently across platforms
- The specific key combination (Ctrl+D vs Ctrl+Z) is handled by the OS and Python runtime
- No platform-specific code required
