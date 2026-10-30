"""
A2A Agent Registry
==================
Directory of every agent in the stack that can be reached over A2A, regardless
of the framework that implements it. Registration is what makes an agent
*discoverable*; the registry is what the `/a2a/agents` directory and each
agent's card endpoint are served from.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from ..utils import observability as obs
from .models import AgentCard, Message, Task, completed_task, failed_task

logger = logging.getLogger("a2a.registry")


class A2AAgent:
    """An agent exposed over A2A. `skills` maps a skill id to its handler."""

    def __init__(self, agent_id: str, card: AgentCard,
                 skills: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]):
        self.agent_id = agent_id
        self.card = card
        self.skills = skills

    def handle(self, message: Message, skill_id: Optional[str] = None) -> Task:
        payload = message.data()
        skill = skill_id or payload.pop("skill", None) or (
            self.card.skills[0].id if self.card.skills else None)

        if skill not in self.skills:
            return failed_task(
                f"Agent '{self.agent_id}' has no skill '{skill}'. "
                f"Available: {sorted(self.skills)}", request=message)

        with obs.span(f"a2a:{self.agent_id}:{skill}", kind="a2a",
                      input={"skill": skill, "framework": self.card.framework}) as sp:
            try:
                result = self.skills[skill](payload)
                sp.set_output(result)
                return completed_task(result, request=message, name=skill)
            except Exception as e:
                logger.exception(f"A2A skill '{skill}' on agent '{self.agent_id}' failed.")
                sp.fail(e)
                return failed_task(f"{type(e).__name__}: {e}", request=message)


class A2ARegistry:
    def __init__(self):
        self._agents: Dict[str, A2AAgent] = {}

    def register(self, agent: A2AAgent) -> A2AAgent:
        self._agents[agent.agent_id] = agent
        logger.info(f"A2A agent registered: {agent.agent_id} "
                    f"({agent.card.framework}, skills={sorted(agent.skills)})")
        return agent

    def get(self, agent_id: str) -> A2AAgent:
        if agent_id not in self._agents:
            raise KeyError(f"Unknown A2A agent '{agent_id}'. Known: {sorted(self._agents)}")
        return self._agents[agent_id]

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def list(self) -> List[A2AAgent]:
        return [self._agents[a] for a in sorted(self._agents)]

    def directory(self) -> List[Dict[str, Any]]:
        return [{"agentId": a.agent_id, "framework": a.card.framework,
                 "cardUrl": f"{a.card.url}/.well-known/agent-card.json",
                 **a.card.to_dict()} for a in self.list()]


registry = A2ARegistry()
