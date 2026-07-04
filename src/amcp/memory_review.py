"""Memory guidance and pre-compaction flush for AMCP.

Two-layer memory strategy:

1. **MEMORY_GUIDANCE** (always on, zero cost): injected into every system
   prompt, tells the LLM when to proactively use the memory tool during
   normal conversation — user preferences → upsert_fact, personality →
   write_soul, identity → identify, etc.

2. **Pre-compaction memory flush** (on-demand): when the conversation is
   about to be compacted (context too large), run a focused LLM call with
   only the memory tool available, asking the agent to save durable
   memories before they get summarized away. Inspired by openclaw's
   pre-compaction flush; lighter than hermes-agent's every-N-turns nudge.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MEMORY_GUIDANCE = """\
<memory_guidance>
You have persistent memory that survives across sessions via the `memory` tool. \
Use it proactively — do not wait for the user to ask.

**When to save:**
- User states a durable preference ("I prefer concise replies", "always use TypeScript") \
→ `memory` action: "write" (append to long-term MEMORY.md) or "upsert_fact"
- User defines your personality or role ("you are a careful pair programmer") \
→ `memory` action: "write_soul"
- User tells you who you are (name, identity, avatar, calling) \
→ `memory` action: "identify" (with content) or "write_identity"
- You discover an important project fact or convention \
→ `memory` action: "append" (to history log) or "upsert_fact"
- User corrects your behavior in a way that should persist \
→ `memory` action: "write" or "upsert_fact"

**When NOT to save:**
- Task progress, completed work, temporary TODO state
- Facts that will be stale in a week (PR numbers, commit SHAs, file counts)
- Procedural workflows (those go in skills, not memory)

**Format:** Write memories as declarative facts, not instructions.
  ✓ "User prefers concise replies"  ✗ "Always respond concisely"
  ✓ "Project uses pytest with xdist"  ✗ "Run tests with pytest -n 4"

**Scope:** Use scope="user" for global preferences, scope="project" for \
project-specific facts. Agent identity and soul are global-only: when the user \
names you, defines who you are, or changes your long-term persona, use \
scope="user" with "identify", "write_identity", or "write_soul" unless they \
explicitly ask you to record a non-persona project fact. Default is "user".

**Searching past context:** When the user references a prior conversation or \
you need cross-session context, use `memory` action: "search" before asking \
the user to repeat themselves.

These persist to disk (SOUL.md, IDENTITY.md, MEMORY.md, memory.db) and are \
loaded automatically in every new session.
</memory_guidance>"""


MEMORY_REVIEW_PROMPT = """\
The conversation is about to be compacted (summarized to save context). \
Before that happens, save any durable memories that would be lost.

Focus on:
1. Has the user revealed things about themselves — their persona, desires, \
preferences, or personal details worth remembering?
2. Has the user expressed expectations about how you should behave, your work \
style, or ways they want you to operate?
3. Has the user defined or updated your identity, name, or soul?
4. Did you discover an important project fact or convention that future \
sessions would benefit from knowing?

If something stands out, save it using the memory tool (action: "write", \
"upsert_fact", "write_soul", "write_identity", or "append").
If nothing is worth saving, reply with exactly "Nothing to save." and stop.

Remember: write memories as declarative facts, not instructions to yourself.\
"""


async def run_memory_review(
    client: Any,
    model: str,
    system_prompt: str,
    conversation_snapshot: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_registry: Any,
    project_root: str | None = None,
) -> str:
    """Run a post-turn memory review.

    Makes LLM call(s) with the conversation snapshot and a focused review
    prompt. The agent can use the memory tool to save durable facts.
    Runs a simple tool-calling loop (up to 5 iterations).

    Args:
        client: LLM client with a .chat() method.
        model: Model name (unused if client already has model set).
        system_prompt: The current system prompt (for context).
        conversation_snapshot: Recent conversation messages.
        tools: Available tool specs (must include memory tool).
        tool_registry: Tool registry for executing tool calls.
        project_root: Current project root for project-scoped memory writes.

    Returns:
        The review result text (or empty string on failure).
    """
    import json

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *conversation_snapshot,
        {"role": "user", "content": MEMORY_REVIEW_PROMPT},
    ]

    try:
        for _ in range(5):
            resp = client.chat(messages=messages, tools=tools)

            if not resp.tool_calls:
                return resp.content or ""

            # Execute tool calls
            for tc in resp.tool_calls:
                tool_name = tc["name"]
                tool_id = tc["id"]
                args = json.loads(tc["arguments"] or "{}")

                # Add assistant message with tool call
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tool_id,
                                "type": "function",
                                "function": {"name": tool_name, "arguments": tc["arguments"]},
                            }
                        ],
                    }
                )

                # Execute the tool
                try:
                    exec_args = args
                    if tool_name == "memory" and project_root:
                        exec_args = {**args, "project_root": project_root}
                    tool_result = tool_registry.execute_tool(tool_name, **exec_args)
                    result_text = tool_result.content if tool_result.success else f"Error: {tool_result.error}"
                except Exception as e:
                    result_text = f"Error: {e}"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "name": tool_name,
                        "content": result_text,
                    }
                )

            # Loop back to let the LLM process tool results

        # Max iterations reached
        return ""
    except Exception as e:
        logger.debug(f"Memory review failed (non-critical): {e}")
        return ""
