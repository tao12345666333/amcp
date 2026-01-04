"""AMCP Prompt Templates Module.

This module provides template-based system prompts for the AMCP agent,
with support for:
- Structured prompt sections (critical_rules, workflow, editing, etc.)
- Model-specific optimizations (Claude, GPT, Gemini)
- Dynamic environment injection (working directory, git status, etc.)
- Skills and memory file integration
"""

from .manager import PromptContext, PromptManager, get_prompt_manager

__all__ = ["PromptManager", "PromptContext", "get_prompt_manager"]
