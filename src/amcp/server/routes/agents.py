"""Agent management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import AgentInfo, AgentListResponse

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=AgentListResponse)
async def list_agents() -> AgentListResponse:
    """List all available agents."""
    from ...multi_agent import AgentMode, get_agent_registry

    registry = get_agent_registry()

    agents = []
    for name, config in registry._agents.items():
        # Check mode properly - AgentConfig has mode as AgentMode enum
        is_subagent = config.mode == AgentMode.SUBAGENT
        agents.append(
            AgentInfo(
                name=name,
                description=config.description or "",
                mode="subagent" if is_subagent else "primary",
                tools_count=len(config.tools) if config.tools else 0,
            )
        )

    return AgentListResponse(agents=agents, total=len(agents))


@router.get("/{agent_name}")
async def get_agent(agent_name: str) -> dict:
    """Get detailed information about an agent."""
    from ...multi_agent import AgentMode, get_agent_registry

    registry = get_agent_registry()
    config = registry.get(agent_name)

    if config is None:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Agent not found: {agent_name}", "code": "AGENT_NOT_FOUND"},
        )

    is_subagent = config.mode == AgentMode.SUBAGENT

    return {
        "name": agent_name,
        "description": config.description or "",
        "mode": "subagent" if is_subagent else "primary",
        "max_steps": config.max_steps,
        "system_prompt_preview": (config.system_prompt[:200] + "...")
        if config.system_prompt and len(config.system_prompt) > 200
        else config.system_prompt,
        "tools": config.tools or [],
        "excluded_tools": config.excluded_tools or [],
        "can_delegate": config.can_delegate,
    }


@router.get("/{agent_name}/spec")
async def get_agent_spec(agent_name: str) -> dict:
    """Get the full agent specification."""
    from ...multi_agent import get_agent_registry

    registry = get_agent_registry()
    config = registry.get(agent_name)

    if config is None:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Agent not found: {agent_name}", "code": "AGENT_NOT_FOUND"},
        )

    return {
        "name": config.name,
        "mode": config.mode.value,
        "description": config.description,
        "max_steps": config.max_steps,
        "system_prompt": config.system_prompt,
        "tools": config.tools or [],
        "excluded_tools": config.excluded_tools or [],
        "can_delegate": config.can_delegate,
    }
