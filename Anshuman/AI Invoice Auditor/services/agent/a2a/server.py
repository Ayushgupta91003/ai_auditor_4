"""
A2A Server
==========
Serves agent discovery and invocation over HTTP:

  GET  /a2a/agents                              directory of every registered agent
  GET  /a2a/{agent_id}/.well-known/agent-card.json   one agent's card
  POST /a2a/{agent_id}                          JSON-RPC 2.0: message/send, tasks/get

The transport is deliberately framework-neutral. A LangGraph node calling the
Google ADK translation agent and an external system calling the same agent send
byte-identical requests.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .models import Message, Task
from .registry import registry

logger = logging.getLogger("a2a.server")

router = APIRouter(prefix="/a2a", tags=["A2A"])

# Completed tasks are retained so `tasks/get` can answer after the fact.
_TASKS: Dict[str, Task] = {}
_TASK_LIMIT = 500


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


def _ok(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _remember(task: Task) -> None:
    _TASKS[task.id] = task
    while len(_TASKS) > _TASK_LIMIT:
        _TASKS.pop(next(iter(_TASKS)))


@router.get("/agents")
def list_agents():
    """Discovery directory: every agent, its framework and its skills."""
    return {"protocolVersion": "0.3.0", "count": len(registry.list()),
            "agents": registry.directory()}


@router.get("/{agent_id}/.well-known/agent-card.json")
@router.get("/{agent_id}/card")
def agent_card(agent_id: str):
    try:
        return registry.get(agent_id).card.to_dict()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{agent_id}")
def agent_rpc(agent_id: str, request: JsonRpcRequest):
    """A2A JSON-RPC entry point for a single agent."""
    try:
        agent = registry.get(agent_id)
    except KeyError as e:
        return _err(request.id, -32602, str(e))

    if request.method in ("message/send", "message/stream"):
        raw_message = request.params.get("message")
        if not raw_message:
            return _err(request.id, -32602, "Missing required parameter 'message'.")
        message = Message.from_dict(raw_message)
        skill = request.params.get("skill") or (request.params.get("metadata") or {}).get("skill")
        task = agent.handle(message, skill_id=skill)
        _remember(task)
        return _ok(request.id, task.to_dict())

    if request.method == "tasks/get":
        task_id = request.params.get("id")
        task = _TASKS.get(task_id)
        if task is None:
            return _err(request.id, -32001, f"Task '{task_id}' not found.")
        return _ok(request.id, task.to_dict())

    if request.method == "agent/getAuthenticatedExtendedCard":
        return _ok(request.id, agent.card.to_dict())

    return _err(request.id, -32601, f"Method not found: {request.method}")
