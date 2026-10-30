"""Agent-to-Agent protocol: discovery, messaging and task exchange."""

from .client import A2AClient, A2AError, a2a_client
from .models import AgentCapabilities, AgentCard, AgentSkill, Message, Part, Task
from .registry import A2AAgent, A2ARegistry, registry as a2a_registry
from .server import router as a2a_router

__all__ = [
    "A2AClient", "A2AError", "a2a_client",
    "AgentCard", "AgentSkill", "AgentCapabilities", "Message", "Part", "Task",
    "A2AAgent", "A2ARegistry", "a2a_registry", "a2a_router",
]
