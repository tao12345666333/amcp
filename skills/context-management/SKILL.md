---
name: context-management
description: Learn how to manage conversation context in AMCP to avoid LLM API errors from exceeding context windows. This skill covers SmartCompactor strategies, token estimation, configuration, and best practices.
---

# Context Management Skill

## Overview

This skill teaches you how to proactively manage your conversation context in AMCP to avoid LLM API errors caused by exceeding context window limits. Context management is critical when:

- Working on long coding sessions with many files
- Processing large tool outputs (e.g., `grep` results, file reads)
- Running multi-step debugging sessions
- Reviewing or refactoring large codebases

## Understanding Context Windows

Different LLM models have different context window sizes:

| Model Family | Context Window |
|--------------|----------------|
| GPT-4 Turbo / GPT-4o | 128,000 tokens |
| GPT-4.1 | 1,000,000 tokens |
| Claude 3.5 Sonnet | 200,000 tokens |
| DeepSeek V3 | 64,000 tokens |
| Gemini 2.0 Flash | 1,000,000 tokens |
| Qwen 2.5 | 128,000 tokens |

AMCP automatically detects most model context windows. For unknown models, it uses 32,000 tokens as the default.

## Key Metrics

When managing context, track:

- **Current tokens**: Estimated size of current conversation history
- **Threshold tokens**: When compaction should trigger (default: 70% of context)
- **Target tokens**: What to aim for after compaction (default: 30% of context)
- **Safety margin**: Reserved for response generation (default: 10%)

## How AMCP Compacts Context

AMCP's `SmartCompactor` automatically compresses context when it exceeds the threshold:

```python
# In agent.py (line 500-505):
compactor = SmartCompactor(client, model)
if compactor.should_compact(history_to_add):
    history_to_add, _ = compactor.compact(history_to_add)
```

**This happens automatically during conversation!** You don't need to trigger it manually.

### Compaction Strategies

AMCP supports four strategies (configurable via `CompactionConfig`):

1. **SUMMARY** (default): Uses LLM to create intelligent summary of old messages
   - Best for: Long sessions where earlier context is important
   - Preserves: Errors, working solutions, current task state, file paths

2. **TRUNCATE**: Simple removal of old messages, keeping first and last few
   - Best for: Fast compaction when context is less important
   - Fastest option

3. **SLIDING_WINDOW**: Keeps only the most recent messages that fit in target
   - Best for: Sessions where only recent context matters
   - Very efficient

4. **HYBRID**: Combines sliding window with summary of removed content
   - Best for: Balance between summary quality and speed

## Best Practices for Context Management

### 1. Read Files Selectively

Instead of reading entire large files:

```python
# BAD: Reads entire file
read_file(path="src/large_module.py")

# GOOD: Read specific sections
read_file(path="src/large_module.py", mode="indentation", offset=100, limit=50)

# GOOD: Read specific line ranges
read_file(path="src/large_module.py", mode="slice", ranges=["1-50", "200-250"])
```

**Use `read_file` in indentation mode** - it intelligently captures code blocks around your target, providing context without excessive content.

### 2. Use Grep with Context Limits

```python
# BAD: Returns all matches with full context
grep(pattern="function", paths=["src/"])

# GOOD: Limited context
grep(pattern="function", paths=["src/"], context=2)
```

### 3. Iterate Over Small Batches

When processing multiple files:

```python
# Instead of processing all files at once:
for file in files:
    # Process one file at a time
    result = process_file(file)
    # Save intermediate results
```

### 4. Clear Conversation When Starting New Tasks

After completing a complex task, consider suggesting:

> "会话历史较长。如果开始新的无关任务，建议清除历史或创建新会话以减少上下文。"

### 5. Be Strategic with Tool Calls

- Avoid redundant tool calls (e.g., reading the same file multiple times)
- Use `grep` to find what you need before reading files
- Process results incrementally rather than all at once

## Monitoring Context Usage

You can check context usage programmatically:

```python
from amcp import SmartCompactor

# Create compactor
compactor = SmartCompactor(client, model="gpt-4-turbo")

# Get detailed usage info
usage = compactor.get_token_usage(messages)
print(f"Current: {usage['current_tokens']:,} tokens")
print(f"Usage: {usage['usage_ratio']:.1%} of context")
print(f"Headroom: {usage['headroom_tokens']:,} tokens")
print(f"Should compact: {usage['should_compact']}")
```

## Configuration

Context compaction is configured via `CompactionConfig`:

```python
from amcp import SmartCompactor, CompactionConfig, CompactionStrategy

config = CompactionConfig(
    strategy=CompactionStrategy.SUMMARY,
    threshold_ratio=0.7,  # Compact at 70% usage
    target_ratio=0.3,     # Aim for 30% after compaction
    preserve_last=6,      # Keep last 6 user/assistant messages
    preserve_tool_results=True,  # Preserve recent tool results
    max_tool_results=10,  # Max tool results to preserve
    min_tokens_to_compact=5000,  # Don't compact tiny contexts
    safety_margin=0.1,    # 10% margin for responses
)
```

You can configure compaction in `~/.config/amcp/config.toml`:

```toml
[chat]
model = "deepseek-chat"

[compaction]
strategy = "summary"  # summary, truncate, sliding_window, hybrid
threshold_ratio = 0.7
target_ratio = 0.3
```

## Automatic Summary Structure

When using SUMMARY or HYBRID strategies, the summary follows this structure:

```xml
<current_task>
What we're working on now - be specific about files and goals
</current_task>

<completed>
- Task 1: Brief outcome + key changes made
- Task 2: Brief outcome + key changes made
</completed>

<code_state>
Key files and their current state - signatures + key logic only
Include file paths that were modified
</code_state>

<important>
Any crucial context: errors, decisions made, constraints, blockers
</important>
```

## Token Estimation

AMCP provides accurate token estimation:

```python
from amcp import estimate_tokens

tokens = estimate_tokens(messages)
```

- Uses `tiktoken` library when available (recommended)
- Falls back to character-based estimation (4 chars ≈ 1 token)
- Accounts for message role overhead

## Common Issues and Solutions

### Issue 1: "Context length exceeded" API Error

**Symptom**: LLM API returns error about context window being exceeded.

**Causes**:
- Large tool outputs (e.g., `grep` or `find` results)
- Reading many large files
- Long multi-step task conversations

**Solutions**:
1. Let AMCP's auto-compaction handle it (it will compact automatically)
2. Reduce tool output size (use `grep --limit`, `read_file` with ranges)
3. Process files in batches, not all at once
4. Suggest clearing conversation history if starting new task

### Issue 2: Context Losing Important Information

**Symptom**: After compaction, agent forgets critical details.

**Causes**:
- SUMMARY strategy missed important context
- Old critical messages were removed

**Solutions**:
1. Use `preserve_last` to keep more recent messages
2. Consider HYBRID strategy (keeps sliding window + summary)
3. Manually restate critical context in your prompt

### Issue 3: Summary Losing Code Details

**Symptom**: Agent forgets specific code changes after compaction.

**Solutions**:
1. Use `preserve_tool_results=True` (default) to keep recent tool outputs
2. Increase `max_tool_results` (default: 10)
3. Review summary and add missing details

## Progressive Disclosure

AMCP uses progressive disclosure to manage skill instructions:

```python
# In skills.py (line 297):
skills_summary = skill_manager.build_skills_summary()
```

This means:
- You only get a compact summary of all skills initially
- Full skill content is available when needed
- Reduces initial context overhead

## Memory System vs Context

AMCP separates:

1. **Conversation Context**: The messages sent to the LLM (limited by context window)
2. **Persistent Memory**: Long-term storage in `.amcp/memory/` (unlimited)

Use the memory system to store important information that should persist long-term:

```python
memory(action="write", content="# Project Notes\n- Uses PostgreSQL database")
```

This information is NOT in the conversation context - it's stored separately and retrieved when relevant.

## Practical Workflow

For complex tasks with large context:

1. **Start**: Use `grep` or `find` to locate relevant files
   ```python
   grep(pattern="class User", paths=["src/"])
   ```

2. **Explore**: Read specific sections using indentation mode
   ```python
   read_file(path="src/models/user.py", mode="indentation", offset=1)
   ```

3. **Process**: Work incrementally, one file at a time
4. **Monitor**: If context gets large, compaction happens automatically
5. **Persist**: Save important findings to memory if needed for future sessions
   ```python
   memory(action="append", content="Found authentication bug in src/auth.py:45")
   ```

## Event Monitoring

AMCP emits events when compaction occurs:

```python
from amcp import get_event_bus, EventType

@get_event_bus().on(EventType.CONTEXT_COMPACTED)
async def on_compaction(event):
    data = event.data
    print(f"Context compacted: {data['original_tokens']} -> {data['compacted_tokens']}")
```

## Key Takeaways

1. **Auto-compaction happens automatically** - you don't need to trigger it
2. **Read files selectively** - use indentation mode or ranges
3. **Monitor context usage** - be aware of large tool outputs
4. **Persist important info to memory** - for long-term retention
5. **Process incrementally** - handle large tasks in steps
6. **Configure as needed** - adjust `CompactionConfig` for your use case

## When to Suggest Clearing Context

If you notice:
- Conversation is very long (>50 messages)
- You're starting a completely different task
- Context from earlier sessions is no longer relevant

Then suggest:

> "会话历史较长。如果开始新的无关任务，建议清除历史或创建新会话以减少上下文。"

This is proactive context management!