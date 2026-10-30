"""
Bootstrap
=========
One import that brings the whole agentic surface online in the right order:

  1. tools         -> populates the MCP tool registry
  2. langgraph A2A -> publishes the LangGraph agents' cards
  3. adk_agents    -> instantiates the Google ADK agents and publishes their cards

Call `bootstrap()` once at service startup. It is idempotent.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger("bootstrap")

_done = False


def bootstrap() -> Dict[str, Any]:
    global _done
    if _done:
        return summary()

    from . import tools  # noqa: F401  registers the eleven tools
    from .a2a import langgraph_agents  # noqa: F401  publishes LangGraph agent cards

    try:
        from . import adk_agents  # noqa: F401  publishes Google ADK agent cards
    except Exception as e:
        logger.error(f"Google ADK agents could not be registered ({e}). "
                     f"A2A discovery will list LangGraph agents only.")

    _done = True
    info = summary()
    logger.info(f"Agentic surface ready: {info['tool_count']} MCP tools, "
                f"{info['agent_count']} A2A agents ({info['frameworks']}).")
    return info


def summary() -> Dict[str, Any]:
    from .tools import registry as tool_registry
    from .a2a.registry import registry as agent_registry

    agents = agent_registry.list()
    frameworks: Dict[str, int] = {}
    for a in agents:
        frameworks[a.card.framework] = frameworks.get(a.card.framework, 0) + 1

    return {
        "tool_count": len(tool_registry.list()),
        "tools": [t.name for t in tool_registry.list()],
        "agent_count": len(agents),
        "agents": [{"agentId": a.agent_id, "framework": a.card.framework,
                    "skills": sorted(a.skills)} for a in agents],
        "frameworks": frameworks,
    }
