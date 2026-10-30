"""
Google ADK agents.

Importing this package instantiates the ADK agents and registers them with the
A2A registry, which is what makes them discoverable at `/a2a/agents`.
"""

from .base import ADKAgent, ADK_ENABLED
from . import translation_agent
from . import business_validation_agent

ADK_AGENT_IDS = [translation_agent.AGENT_ID, business_validation_agent.AGENT_ID]

__all__ = ["ADKAgent", "ADK_ENABLED", "ADK_AGENT_IDS",
           "translation_agent", "business_validation_agent"]
