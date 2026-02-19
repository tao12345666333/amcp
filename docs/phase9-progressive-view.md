# AMCP Phase 9: Progressive Context View (Optimized + MVP Implemented)

## Conclusion (Is the approach reasonable?)

The original direction was correct, but several parts did not match the current codebase:

1. Tool names did not match real implementations (for example, `grep_search` / `list_dir` do not exist).
2. Budget allocation was not aligned with the current `Agent` flow (`_get_system_prompt`, `_build_tools_and_registry`).
3. Skill loading was too heavy and lacked clear automatic downgrade behavior when budget is tight.
4. Observability events and CLI output were idealized and not mapped to existing event structures.

This document has been rewritten into an executable MVP plan aligned with the current architecture, and it is now implemented.

---

## Design Goals (unchanged)

- Reduce system-context size per request
- Expose tools/skills on demand without losing core capabilities
- Make budget allocation configurable, observable, and reversible

---

## Implemented Scope (MVP)

### New modules

```text
src/amcp/progressive/
├── __init__.py
├── context_budget.py   # Budget allocation and text token estimation
├── relevance.py        # Task classification and tool/skill relevance scoring
├── tool_view.py        # Tool tiering + budget-aware selection
├── skill_view.py       # Progressive skill loading: FULL/OVERVIEW/SUMMARY
└── usage_tracker.py    # recency/frequency/cooccurrence from tool_calls history
```

### Integrated into `Agent`

1. `Agent._get_system_prompt(...)`
   - Adds budget calculation
   - Loads skill content progressively within budget
   - Trims memory/rules by budget
2. `Agent._build_tools_and_registry(...)`
   - Applies progressive tool filtering after combining built-in + MCP tools
   - Supports `tool_tiers` overrides
   - Emits filtering events for observability

---

## Key Improvements

## 1) Tool tiers corrected to actual tool set

Default tiers (configurable):

- `ALWAYS`: `read_file`, `grep`, `think`
- `FREQUENT`: `apply_patch`, `write_file`, `bash`, `todo`
- `ON_DEMAND`: `memory`, `task`, `mcp.*`
- `HIDDEN`: only when explicitly set via `tool_tiers`

> This is safer than forcing write tools into `ALWAYS`: it preserves implementation capability while reducing irrelevant noise.

## 2) Budget model updated to “reserve base first, split remaining by ratio”

```text
prompt_budget = max(model_window - response_reserve - conversation_tokens, min_prompt_budget)
base_prompt   = min(base_prompt_max_tokens, prompt_budget)
allocatable   = prompt_budget - base_prompt
tools/skills/memory/rules split allocatable by normalized ratios
```

This avoids base-prompt starvation and prevents malformed ratio settings from breaking allocation.

## 3) Skill progressive downgrade is now explicit

Loading order:

1. Active skills: FULL first, then OVERVIEW, then SUMMARY if needed
2. Non-active skills: include OVERVIEW by relevance
3. Remaining skills: append SUMMARY list when budget allows

## 4) Usage history is session-only (no persistence yet)

`usage_tracker.py` computes from existing `tool_calls_history`:

- recency (exponential decay)
- frequency (normalized)
- cooccurrence (adjacent call pairs)

This validates effect with low implementation cost before deciding on persistence.

---

## Configuration (supported)

```toml
[context]
progressive_tools = true
progressive_skills = true

response_ratio = 0.30
min_prompt_budget = 2500
base_prompt_max_tokens = 2200

tool_budget_ratio = 0.45
skill_budget_ratio = 0.30
memory_budget_ratio = 0.15
rules_budget_ratio = 0.10

tool_relevance_threshold = 0.12
skill_relevance_threshold = 0.25

[context.tool_tiers]
read_file = "always"
grep = "always"
think = "always"
apply_patch = "frequent"
write_file = "frequent"
bash = "frequent"
todo = "frequent"
memory = "on_demand"
task = "on_demand"
mcp.* = "on_demand"
```

---

## Integration points in current flow

1. In `_process_message`:
   - Pass `user_input` when building system prompt
   - Pass `user_input + conversation_history` when building tools

2. In `_get_system_prompt`:
   - Calculate budget
   - Render skills progressively
   - Trim rules/memory

3. In `_build_tools_and_registry`:
   - Respect `agent_spec.tools / exclude_tools` first
   - Apply progressive filtering afterward

---

## Observability (MVP)

Current agent callback events:

- `context.budget_allocated`
- `context.tools_filtered`

Later, these can be mapped into the unified `EventType` enum.

---

## Test coverage (added)

- `tests/test_progressive.py`
  - Stable budget allocation
  - Always-tier guarantees
  - Skill downgrade under small budget
- `tests/test_agent_progressive.py`
  - Agent-level progressive tool filtering integration
- `tests/test_config.py`
  - `context` config decode/encode regression

---

## Future optimization opportunities

1. Replace `len(text)//4` with a real tokenizer.
2. Merge `context.*` events into `event_bus.EventType`.
3. Add `amcp context stats` for runtime diagnostics.
4. Introduce cross-session usage persistence and cold-start strategy.

---

## Version note

The MVP target version for Progressive Context View remains **AMCP v0.12.0**.
