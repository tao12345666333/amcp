# AMCP Phase 9: Progressive Tool/Skill View (Context Optimization)

Intelligent context management that dynamically loads and unloads tool descriptions and skill content based on relevance, reducing token usage while maintaining agent capability.

## Motivation

As AMCP grows, the system prompt expands significantly:

| Component | Current Size (est.) | Growth Rate |
|-----------|-------------------|-------------|
| Base system prompt | ~2,000 tokens | Stable |
| Tool descriptions (15+ tools) | ~3,000 tokens | Per tool added |
| Skill content (when active) | ~2,000-5,000 tokens | Per skill |
| Memory context | ~500-1,000 tokens | Grows over time |
| Project rules (AGENTS.md) | ~500-1,000 tokens | Per project |
| **Total** | **~8,000-12,000 tokens** | **Growing** |

With Heartbeat + Cron running frequent autonomous tasks, every wasted token multiplies across hundreds of daily API calls. Progressive View addresses this by:

- **Reducing cost**: Only include relevant tool/skill descriptions in each call
- **Improving quality**: Less noise in the system prompt → better agent focus
- **Scaling gracefully**: Support 50+ tools and 20+ skills without context bloat
- **Adapting dynamically**: Learn which tools are relevant for different task types

## Architecture

### High-Level Design

```
┌────────────────────────────────────────────────────────────────┐
│                    System Prompt Assembly                       │
│                                                                │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────────────┐│
│  │  Static   │  │  Progressive │  │    Progressive Skill     ││
│  │  Base     │  │  Tool View   │  │    View                  ││
│  │  Prompt   │  │              │  │                          ││
│  └────┬─────┘  └──────┬───────┘  └───────────┬───────────────┘│
│       │               │                      │                │
│       └───────┬───────┴──────────────────────┘                │
│               │                                               │
│       ┌───────▼────────┐                                      │
│       │  Context       │                                      │
│       │  Budget        │◀── Token limit based on model        │
│       │  Manager       │                                      │
│       └───────┬────────┘                                      │
│               │                                               │
│       ┌───────▼────────┐                                      │
│       │  Relevance     │◀── User input + conversation history │
│       │  Scorer        │                                      │
│       └────────────────┘                                      │
└────────────────────────────────────────────────────────────────┘
```

### Component Breakdown

```
src/amcp/
├── progressive/
│   ├── __init__.py
│   ├── context_budget.py    # Token budget allocation
│   ├── tool_view.py         # Progressive tool description loading
│   ├── skill_view.py        # Progressive skill content loading
│   ├── relevance.py         # Relevance scoring engine
│   └── usage_tracker.py     # Tool usage analytics for learning
```

## Core Concepts

### 1. Tool Tiers

Tools are organized into tiers based on universal necessity:

```python
class ToolTier(StrEnum):
    """Tool importance tiers."""
    ALWAYS = "always"       # Always included (core tools)
    FREQUENT = "frequent"   # Included by default, can be hidden
    ON_DEMAND = "on_demand" # Only included when relevant
    HIDDEN = "hidden"       # Never auto-included, user must request
```

Default tier assignments:

| Tier | Tools | Rationale |
|------|-------|-----------|
| **ALWAYS** | `bash`, `read_file`, `write_file`, `think` | Core agent capabilities |
| **FREQUENT** | `grep_search`, `list_dir`, `apply_patch`, `memory` | Commonly needed |
| **ON_DEMAND** | `task`, `todo`, `mcp_*` | Situational |
| **HIDDEN** | Rarely used MCP tools | Only on explicit request |

### 2. Skill Loading Levels

Skills have three levels of context inclusion:

```python
class SkillLoadLevel(StrEnum):
    """How much skill content to include."""
    SUMMARY = "summary"       # One-line description only (~20 tokens)
    OVERVIEW = "overview"     # Name + description + key capabilities (~100 tokens)
    FULL = "full"             # Complete SKILL.md content (~500-2000 tokens)
```

### 3. Context Budget

The context budget determines how many tokens are allocated to tool descriptions and skill content:

```python
@dataclass
class ContextBudget:
    """Token budget for system prompt components."""
    total_available: int          # Model context window
    reserved_for_response: float  # % reserved for response (default 30%)
    reserved_for_history: float   # % reserved for conversation (default 40%)
    prompt_budget: int            # Remaining for system prompt

    # Sub-budgets within system prompt
    base_prompt: int              # Fixed base prompt
    tools: int                    # Tool descriptions
    skills: int                   # Skill content
    memory: int                   # Memory context
    rules: int                    # Project rules
```

## Implementation Details

### Context Budget Manager

```python
class ContextBudgetManager:
    """Allocate token budget across system prompt components."""

    def __init__(self, model: str, config: ContextConfig | None = None):
        self.model_window = get_model_context_window(model)
        self.config = config or ContextConfig()

    def calculate_budget(self, conversation_tokens: int) -> ContextBudget:
        """Calculate available budget given current conversation size."""
        # Reserve space for response generation
        response_reserve = int(self.model_window * self.config.response_ratio)

        # Available for prompt + conversation
        available = self.model_window - response_reserve

        # Budget for system prompt = available - conversation
        prompt_budget = max(
            available - conversation_tokens,
            self.config.min_prompt_budget,
        )

        # Allocate sub-budgets proportionally
        return ContextBudget(
            total_available=self.model_window,
            prompt_budget=prompt_budget,
            base_prompt=min(2000, prompt_budget),
            tools=int(prompt_budget * 0.35),    # 35% for tools
            skills=int(prompt_budget * 0.25),   # 25% for skills
            memory=int(prompt_budget * 0.15),   # 15% for memory
            rules=int(prompt_budget * 0.10),    # 10% for rules
            # 15% buffer for accurate estimation gaps
        )
```

### Relevance Scorer

```python
class RelevanceScorer:
    """Score tool/skill relevance to current context."""

    def score_tool(
        self,
        tool: BaseTool,
        user_input: str,
        conversation_history: list[dict],
        usage_stats: ToolUsageStats,
    ) -> float:
        """Score tool relevance (0.0 to 1.0)."""
        score = 0.0

        # 1. Keyword matching (0-0.3)
        keywords = self._extract_keywords(tool)
        input_words = set(user_input.lower().split())
        overlap = len(keywords & input_words) / max(len(keywords), 1)
        score += overlap * 0.3

        # 2. Recent usage frequency (0-0.3)
        recency_score = usage_stats.get_recency_score(tool.name)
        score += recency_score * 0.3

        # 3. Co-occurrence with other tools (0-0.2)
        # If tool A was often used with tool B, and B is relevant...
        cooccurrence = usage_stats.get_cooccurrence_score(tool.name)
        score += cooccurrence * 0.2

        # 4. Task type matching (0-0.2)
        task_type = self._classify_task(user_input)
        task_match = self._tool_task_affinity(tool.name, task_type)
        score += task_match * 0.2

        return min(score, 1.0)

    def score_skill(
        self,
        skill: SkillInfo,
        user_input: str,
        active_skills: set[str],
    ) -> float:
        """Score skill relevance (0.0 to 1.0)."""
        if skill.name in active_skills:
            return 1.0  # Always include active skills at full level

        score = 0.0

        # Keyword matching against skill description
        if any(kw in user_input.lower() for kw in skill.keywords):
            score += 0.6

        # Check if skill was recently used
        score += self._recent_skill_usage(skill.name) * 0.4

        return min(score, 1.0)

    def _classify_task(self, user_input: str) -> str:
        """Classify task type from user input."""
        patterns = {
            "code_review": ["review", "pr", "pull request", "diff"],
            "debugging": ["error", "bug", "fix", "fail", "broken"],
            "exploration": ["find", "search", "where", "list", "show"],
            "implementation": ["create", "implement", "add", "build", "write"],
            "ci_cd": ["ci", "pipeline", "deploy", "build", "test"],
            "git": ["commit", "branch", "merge", "rebase", "push"],
        }
        for task_type, keywords in patterns.items():
            if any(kw in user_input.lower() for kw in keywords):
                return task_type
        return "general"
```

### Progressive Tool View

```python
class ProgressiveToolView:
    """Dynamically select which tool descriptions to include."""

    def __init__(
        self,
        registry: ToolRegistry,
        scorer: RelevanceScorer,
        budget_manager: ContextBudgetManager,
    ):
        self.registry = registry
        self.scorer = scorer
        self.budget_manager = budget_manager
        self.tier_config = DEFAULT_TIER_CONFIG

    def get_tool_specs(
        self,
        user_input: str,
        conversation: list[dict],
        usage_stats: ToolUsageStats,
        budget: ContextBudget,
    ) -> list[dict]:
        """Get tool specs that fit within the budget."""
        tools = list(self.registry._tools.values())

        # 1. Always include ALWAYS-tier tools
        always_tools = [t for t in tools if self._get_tier(t) == ToolTier.ALWAYS]
        remaining_budget = budget.tools - self._estimate_tokens(always_tools)

        # 2. Score remaining tools
        scored = []
        for tool in tools:
            if self._get_tier(tool) == ToolTier.ALWAYS:
                continue
            if self._get_tier(tool) == ToolTier.HIDDEN:
                continue
            score = self.scorer.score_tool(tool, user_input, conversation, usage_stats)
            scored.append((tool, score))

        # 3. Sort by score, include top tools within budget
        scored.sort(key=lambda x: x[1], reverse=True)

        selected = list(always_tools)
        for tool, score in scored:
            tool_tokens = self._estimate_tool_tokens(tool)
            if tool_tokens <= remaining_budget and score > 0.1:
                selected.append(tool)
                remaining_budget -= tool_tokens

        # 4. Add a "hidden tools" hint for the agent
        hidden_count = len(tools) - len(selected)
        if hidden_count > 0:
            # Append a note to system prompt
            self._hidden_hint = (
                f"\n\nNote: {hidden_count} additional tools are available "
                f"but not shown. If you need a specific tool not listed above, "
                f"ask the user or describe what you need."
            )

        return [t.get_spec() for t in selected]
```

### Progressive Skill View

```python
class ProgressiveSkillView:
    """Dynamically load skill content at appropriate detail levels."""

    def get_skills_prompt(
        self,
        user_input: str,
        active_skills: set[str],
        budget: ContextBudget,
    ) -> str:
        """Generate skills section of system prompt within budget."""
        skills = self.skill_manager.list_skills()
        remaining = budget.skills

        sections = []

        # 1. Active skills at FULL level
        for skill in skills:
            if skill.name in active_skills:
                content = skill.get_full_content()
                tokens = estimate_tokens_simple(content)
                if tokens <= remaining:
                    sections.append(content)
                    remaining -= tokens
                else:
                    # Fall back to overview if full doesn't fit
                    overview = skill.get_overview()
                    sections.append(overview)
                    remaining -= estimate_tokens_simple(overview)

        # 2. Relevant skills at OVERVIEW level
        for skill in skills:
            if skill.name in active_skills:
                continue
            score = self.scorer.score_skill(skill, user_input, active_skills)
            if score > 0.3:
                overview = skill.get_overview()
                tokens = estimate_tokens_simple(overview)
                if tokens <= remaining:
                    sections.append(overview)
                    remaining -= tokens

        # 3. Remaining skills at SUMMARY level
        summaries = []
        for skill in skills:
            if any(skill.name in s for s in sections):
                continue
            summaries.append(f"- {skill.name}: {skill.description}")

        if summaries:
            summary_block = "Other available skills:\n" + "\n".join(summaries)
            sections.append(summary_block)

        return "\n\n".join(sections)
```

### Usage Tracker

```python
class ToolUsageTracker:
    """Track tool usage patterns for relevance learning."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self._usage: dict[str, ToolUsageStats] = {}

    def record_usage(
        self,
        tool_name: str,
        user_input: str,
        session_id: str,
        success: bool,
    ):
        """Record a tool usage event."""
        stats = self._usage.setdefault(tool_name, ToolUsageStats(tool_name))
        stats.total_calls += 1
        stats.last_used = datetime.now()
        stats.recent_inputs.append(user_input[:100])
        if len(stats.recent_inputs) > 50:
            stats.recent_inputs.pop(0)

    def get_recency_score(self, tool_name: str) -> float:
        """Score based on how recently a tool was used (0-1)."""
        stats = self._usage.get(tool_name)
        if not stats or not stats.last_used:
            return 0.0

        age = (datetime.now() - stats.last_used).total_seconds()
        # Decay: 1.0 at 0s, 0.5 at 5min, 0.1 at 30min, ~0 at 2h
        return max(0.0, 1.0 * (0.5 ** (age / 300)))

    def get_cooccurrence_score(self, tool_name: str) -> float:
        """Score based on co-occurrence with recently used tools."""
        # Tools often used together get higher scores
        ...

    def save(self):
        """Persist usage stats to disk."""
        ...
```

## Configuration

```toml
[context]
# Progressive view settings
progressive_tools = true     # Enable progressive tool view
progressive_skills = true    # Enable progressive skill view

# Budget allocation (ratios of system prompt budget)
tool_budget_ratio = 0.35     # 35% for tool descriptions
skill_budget_ratio = 0.25    # 25% for skill content
memory_budget_ratio = 0.15   # 15% for memory context
rules_budget_ratio = 0.10    # 10% for project rules

# Relevance thresholds
tool_relevance_threshold = 0.1    # Min score to include a tool
skill_relevance_threshold = 0.3   # Min score to show skill overview

# Tool tier overrides
[context.tool_tiers]
bash = "always"
read_file = "always"
write_file = "always"
think = "always"
memory = "frequent"
task = "on_demand"
```

## Agent Integration

### Modified System Prompt Assembly

```python
class Agent:
    def _get_system_prompt(self, work_dir, user_input=None):
        """Build system prompt with progressive views."""
        # Calculate budget
        conv_tokens = estimate_tokens(self.conversation_history)
        budget = self.budget_manager.calculate_budget(conv_tokens)

        # Base prompt (always included)
        prompt = self.resolved_spec.system_prompt

        # Progressive tool descriptions
        # (tool specs are handled separately in API call)

        # Progressive skill content
        if self.progressive_skill_view:
            skills_section = self.progressive_skill_view.get_skills_prompt(
                user_input=user_input or "",
                active_skills=self.active_skills,
                budget=budget,
            )
            if skills_section:
                prompt += f"\n\n{skills_section}"

        # Memory context (trimmed to budget)
        memory_ctx = self.memory_manager.get_memory_context()
        if memory_ctx:
            trimmed = self._trim_to_budget(memory_ctx, budget.memory)
            prompt += f"\n\n{trimmed}"

        # Project rules (trimmed to budget)
        rules = self._load_project_rules(work_dir)
        if rules:
            trimmed = self._trim_to_budget(rules, budget.rules)
            prompt += f"\n\n{trimmed}"

        return prompt
```

## Observability

### Metrics

```python
# Emitted via Event Bus
EventType.CONTEXT_BUDGET_ALLOCATED  # Budget breakdown per request
EventType.TOOLS_FILTERED            # Which tools were included/excluded
EventType.SKILL_LOAD_LEVEL_CHANGED  # Skill loaded at different level
```

### CLI Command

```bash
# View current context usage
amcp context stats

# Output:
#   Model: gpt-4-turbo (128K context)
#   Conversation: 12,340 tokens (9.6%)
#   System Prompt: 4,280 tokens (3.3%)
#     - Base: 1,800 tokens
#     - Tools: 1,200 tokens (8/15 tools shown)
#     - Skills: 680 tokens (2 full, 3 overview, 5 summary)
#     - Memory: 400 tokens
#     - Rules: 200 tokens
#   Available for response: 38,400 tokens (30.0%)
#   Headroom: 72,980 tokens (57.0%)
```

## Testing Strategy

```python
class TestContextBudgetManager:
    def test_budget_calculation(self): ...
    def test_min_budget_enforced(self): ...
    def test_adapts_to_conversation_size(self): ...

class TestRelevanceScorer:
    def test_keyword_matching(self): ...
    def test_recency_scoring(self): ...
    def test_task_classification(self): ...
    def test_cooccurrence(self): ...

class TestProgressiveToolView:
    def test_always_tools_included(self): ...
    def test_budget_respected(self): ...
    def test_hidden_tools_excluded(self): ...
    def test_relevance_ordering(self): ...

class TestProgressiveSkillView:
    def test_active_skills_full(self): ...
    def test_relevant_skills_overview(self): ...
    def test_remaining_skills_summary(self): ...
    def test_budget_fallback(self): ...
```

## Version

Progressive Tool/Skill View is planned for **AMCP v0.12.0**.
