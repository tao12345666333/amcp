# AMCP Phase 4: Smart Compaction

This document describes the Smart Compaction feature implemented in AMCP v0.4.0, which provides intelligent context compaction based on model context window sizes.

## Overview

Smart Compaction automatically manages conversation context length by:

1. **Detecting model context windows** - Automatically determines the context window size for 40+ popular models
2. **Dynamic thresholds** - Calculates compaction thresholds based on the model's capacity
3. **Multiple strategies** - Supports summary, truncate, sliding window, and hybrid strategies
4. **Token estimation** - Uses tiktoken when available for accurate token counting
5. **Event integration** - Emits events when compaction occurs for monitoring

## Model Context Windows

AMCP knows the context window sizes for many popular models:

| Model Family | Models | Context Window |
|--------------|--------|----------------|
| **GPT-4** | gpt-4 | 8,192 |
| **GPT-4 Turbo** | gpt-4-turbo, gpt-4o, gpt-4o-mini | 128,000 |
| **GPT-4.1** | gpt-4.1 | 1,000,000 |
| **Claude 3** | claude-3-opus, claude-3-sonnet, claude-3.5-sonnet | 200,000 |
| **Gemini** | gemini-1.5-pro | 2,000,000 |
| **Gemini** | gemini-1.5-flash, gemini-2.0-flash | 1,000,000 |
| **DeepSeek** | deepseek-v3, deepseek-chat, deepseek-reasoner | 64,000 |
| **Qwen** | qwen-2.5, qwen-max | 128,000 |
| **GLM** | glm-4, glm-4.6 | 128,000 |
| **Mistral** | mistral-large | 128,000 |
| **LLaMA** | llama-3.1-405b, llama-3.2 | 128,000 |

For unknown models, a default of 32,000 tokens is used.

## How It Works

### Dynamic Thresholds

The SmartCompactor calculates thresholds based on the model's context window:

```python
from amcp import SmartCompactor

# For gpt-4-turbo (128K context):
compactor = SmartCompactor(client, model="gpt-4-turbo")
# threshold = 80,640 tokens (70% of available context)
# target = 34,560 tokens (30% after compaction)

# For gpt-4 (8K context):
compactor = SmartCompactor(client, model="gpt-4")
# threshold = 5,160 tokens
# target = 2,211 tokens
```

### Configuration

Customize compaction behavior with `CompactionConfig`:

```python
from amcp import SmartCompactor, CompactionConfig, CompactionStrategy

config = CompactionConfig(
    strategy=CompactionStrategy.SUMMARY,  # summary, truncate, sliding_window, hybrid
    threshold_ratio=0.7,  # Compact when > 70% of context used
    target_ratio=0.3,     # Aim for 30% after compaction
    preserve_last=6,      # Keep last 6 user/assistant messages
    preserve_tool_results=True,  # Preserve recent tool results
    max_tool_results=10,  # Maximum tool results to preserve
    min_tokens_to_compact=5000,  # Don't compact tiny contexts
    safety_margin=0.1,    # 10% margin for response generation
)

compactor = SmartCompactor(client, model="gpt-4-turbo", config=config)
```

## Compaction Strategies

### 1. Summary (Default)

Uses the LLM to create an intelligent summary of old context:

```python
config = CompactionConfig(strategy=CompactionStrategy.SUMMARY)
```

**Best for**: Long coding sessions where context from earlier conversations is important.

The summary is structured:
```
<current_task>
What we're working on now
</current_task>

<completed>
- Task 1: Outcome
- Task 2: Outcome
</completed>

<code_state>
Key files and their current state
</code_state>

<important>
Critical context, errors, decisions made
</important>
```

### 2. Truncate

Simple removal of old messages, keeping first and last few:

```python
config = CompactionConfig(strategy=CompactionStrategy.TRUNCATE)
```

**Best for**: Fast compaction when context is less important.

### 3. Sliding Window

Keeps the most recent messages that fit in the target size:

```python
config = CompactionConfig(strategy=CompactionStrategy.SLIDING_WINDOW)
```

**Best for**: Sessions where only recent context matters.

### 4. Hybrid

Combines sliding window with a summary of removed content:

```python
config = CompactionConfig(strategy=CompactionStrategy.HYBRID)
```

**Best for**: Balance between summary quality and speed.

## Usage Examples

### Basic Usage

```python
from amcp import SmartCompactor, get_model_context_window

# Check model's context window
window = get_model_context_window("gpt-4-turbo")
print(f"Context window: {window:,} tokens")

# Create compactor
compactor = SmartCompactor(client, model="gpt-4-turbo")

# Check if compaction is needed
if compactor.should_compact(messages):
    compacted_messages, result = compactor.compact(messages)
    print(f"Reduced from {result.original_tokens} to {result.compacted_tokens}")
```

### Token Usage Monitoring

```python
# Get detailed token usage
usage = compactor.get_token_usage(messages)
print(f"Current: {usage['current_tokens']:,} tokens")
print(f"Usage: {usage['usage_ratio']:.1%} of context")
print(f"Headroom: {usage['headroom_tokens']:,} tokens")
print(f"Should compact: {usage['should_compact']}")
```

### Factory Function

```python
from amcp import create_compactor

# Quick creation with custom settings
compactor = create_compactor(
    client,
    model="gpt-4-turbo",
    strategy="hybrid",
    threshold_ratio=0.8,
    target_ratio=0.4,
)
```

### Event Monitoring

```python
from amcp import get_event_bus, EventType

@get_event_bus().on(EventType.CONTEXT_COMPACTED)
async def on_compaction(event):
    data = event.data
    print(f"Context compacted: {data['original_tokens']} -> {data['compacted_tokens']}")
    print(f"Strategy: {data['strategy']}")
    print(f"Model: {data['model']}")
```

## Token Estimation

AMCP provides accurate token estimation:

```python
from amcp import estimate_tokens

messages = [
    {"role": "user", "content": "Hello, how are you?"},
    {"role": "assistant", "content": "I'm doing well, thank you!"},
]

tokens = estimate_tokens(messages)
print(f"Estimated tokens: {tokens}")
```

Features:
- Uses `tiktoken` library when available (recommended)
- Falls back to character-based estimation (4 chars ≈ 1 token)
- Accounts for message role overhead
- Counts tool calls separately

To get accurate estimation, install tiktoken:
```bash
pip install tiktoken
```

## Compaction Result

The `compact()` method returns a `CompactionResult` with details:

```python
messages, result = compactor.compact(messages)

print(f"Original tokens: {result.original_tokens}")
print(f"Compacted tokens: {result.compacted_tokens}")  
print(f"Messages removed: {result.messages_removed}")
print(f"Messages preserved: {result.messages_preserved}")
print(f"Strategy used: {result.strategy_used.value}")
print(f"Summary: {result.summary[:100]}...")  # If summary strategy
```

## Integration with Agent

The SmartCompactor is integrated into the Agent class and is used automatically during long conversations. Configure via `config.toml`:

```toml
[chat]
model = "gpt-4-turbo"
# Compaction is automatic based on model's context window
```

## Best Practices

1. **Choose the right strategy**:
   - Use `SUMMARY` for important context
   - Use `TRUNCATE` for speed
   - Use `HYBRID` for balance

2. **Adjust thresholds based on use case**:
   - Lower threshold (0.5-0.6) for frequent compaction
   - Higher threshold (0.8-0.9) for maximum context usage

3. **Preserve recent context**:
   - Keep `preserve_last` at 4-8 for conversation continuity
   - Enable `preserve_tool_results` for coding tasks

4. **Monitor compaction events**:
   - Subscribe to `CONTEXT_COMPACTED` events
   - Log compaction statistics for debugging

## Version

Smart Compaction was added in **AMCP v0.4.0**.
