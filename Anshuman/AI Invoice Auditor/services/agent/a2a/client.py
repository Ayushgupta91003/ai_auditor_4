"""
A2A Client
==========
Used by one agent to call another. Discovery first (fetch the agent card, check
the skill exists), then invocation via `message/send`.

Transport mirrors the MCP client: HTTP when ``A2A_BASE_URL`` is set, otherwise
in-process dispatch against the local registry. Both paths exchange the same
A2A envelope, so moving an agent into its own container is a configuration
change rather than a code change.
"""

import os
import logging
import itertools
from typing import Any, Dict, List, Optional

from .models import Message, Task

logger = logging.getLogger("a2a.client")

A2A_BASE_URL = os.getenv("A2A_BASE_URL", "").strip()
A2A_TIMEOUT = float(os.getenv("A2A_TIMEOUT", "180"))
_ids = itertools.count(1)


class A2AError(RuntimeError):
    """Raised when a remote agent rejects or fails a task."""


class A2AClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url if base_url is not None else A2A_BASE_URL).rstrip("/")

    # -- discovery -------------------------------------------------------------
    def discover(self) -> List[Dict[str, Any]]:
        if self.base_url:
            import httpx
            resp = httpx.get(f"{self.base_url}/a2a/agents", timeout=A2A_TIMEOUT)
            resp.raise_for_status()
            return resp.json().get("agents", [])
        from .registry import registry
        return registry.directory()

    def get_card(self, agent_id: str) -> Dict[str, Any]:
        if self.base_url:
            import httpx
            resp = httpx.get(f"{self.base_url}/a2a/{agent_id}/.well-known/agent-card.json",
                             timeout=A2A_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        from .registry import registry
        return registry.get(agent_id).card.to_dict()

    def supports(self, agent_id: str, skill_id: str) -> bool:
        try:
            card = self.get_card(agent_id)
        except Exception:
            return False
        return any(s.get("id") == skill_id for s in card.get("skills", []))

    # -- invocation ------------------------------------------------------------
    def send(self, agent_id: str, skill: str, payload: Dict[str, Any],
             *, text: str = "", context_id: Optional[str] = None) -> Dict[str, Any]:
        """Sends one A2A message and returns the completed task's data artifact."""
        message = Message.of(payload, text=text)
        message.contextId = context_id
        params = {"message": message.to_dict(), "skill": skill,
                  "metadata": {"skill": skill}}
        request = {"jsonrpc": "2.0", "id": next(_ids), "method": "message/send", "params": params}

        if self.base_url:
            import httpx
            resp = httpx.post(f"{self.base_url}/a2a/{agent_id}", json=request, timeout=A2A_TIMEOUT)
            resp.raise_for_status()
            envelope = resp.json()
        else:
            from .server import agent_rpc, JsonRpcRequest
            envelope = agent_rpc(agent_id, JsonRpcRequest(**request))

        if "error" in envelope:
            raise A2AError(f"A2A error from '{agent_id}': {envelope['error'].get('message')}")

        task = Task.from_dict(envelope.get("result", {}))
        if task.status.state != "completed":
            detail = task.status.message.text() if task.status.message else task.status.state
            raise A2AError(f"Agent '{agent_id}' did not complete skill '{skill}': {detail}")
        return task.result()

    def try_send(self, agent_id: str, skill: str, payload: Dict[str, Any],
                 default: Any = None, **kwargs) -> Any:
        """Non-raising variant: used where a local fallback exists."""
        try:
            return self.send(agent_id, skill, payload, **kwargs)
        except Exception as e:
            logger.warning(f"A2A call {agent_id}.{skill} failed ({e}). Falling back locally.")
            return default


a2a_client = A2AClient()
