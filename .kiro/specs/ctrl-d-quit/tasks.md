# Implementation Plan

- [x] 1. Add EOFError handling to interactive loop
  - Modify the interactive loop in `src/amcp/cli.py` to catch `EOFError` exception
  - Add exception handler alongside existing `KeyboardInterrupt` handler
  - Display goodbye message using same format as explicit exit commands
  - Break from loop to trigger normal cleanup sequence
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ] 2. Set up testing infrastructure
  - Add pytest and hypothesis to project dependencies in `pyproject.toml`
  - Create `tests/` directory structure
  - Create `tests/test_cli.py` for CLI tests
  - Set up test fixtures for mocking console input
  - _Requirements: All (testing infrastructure)_

- [ ] 3. Write property-based tests for EOF handling
  - [ ] 3.1 Write property test for graceful exit on EOF
    - **Property 1: EOF signal triggers graceful exit**
    - **Validates: Requirements 1.1, 1.2**
  
  - [ ] 3.2 Write property test for conversation history persistence
    - **Property 2: Conversation history persists on EOF exit**
    - **Validates: Requirements 1.3**
  
  - [ ] 3.3 Write property test for cleanup equivalence
    - **Property 3: EOF exit performs same cleanup as explicit exit**
    - **Validates: Requirements 1.4**
  
  - [ ] 3.4 Write property test for backward compatibility
    - **Property 4: Backward compatibility maintained**
    - **Validates: Requirements 1.5**

- [ ] 4. Write unit tests for EOF handling
  - Test EOF exception is caught and handled gracefully
  - Test goodbye message is displayed on EOF
  - Test existing exit commands ('exit', 'quit', 'q') still work
  - Test conversation history is saved before exit
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ] 5. Manual verification
  - Run the agent in interactive mode and test Ctrl+D on Unix/Linux/macOS
  - Verify goodbye message appears
  - Verify conversation history is saved
  - Verify existing exit commands still work
  - _Requirements: All_
