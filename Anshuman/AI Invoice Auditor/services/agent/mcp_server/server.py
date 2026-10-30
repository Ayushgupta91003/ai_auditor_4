"""
MCP Server
==========
Exposes the tool registry over the Model Context Protocol so agents *discover*
tools at run time instead of importing them.

Two transports are served from the same registry:

  HTTP (JSON-RPC 2.0)  mounted by the agent service at ``/mcp`` — this is what
                       the in-stack agents and the dashboard use.
  stdio                ``python -m services.agent.mcp_server.server`` — lets any
                       external MCP host (IDE, Claude Desktop, another agent
                       framework) attach to the same tools.

Only the protocol envelope lives here; the capabilities themselves are declared
in ``services/agent/tools``.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..tools import registry
from ..utils import observability as obs

logger = logging.getLogger("mcp.server")

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "invoice-auditor-mcp", "version": "1.0.0"}

router = APIRouter(prefix="/mcp", tags=["MCP"])


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


def _result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def dispatch(method: str, params: Dict[str, Any], req_id: Any = None) -> Dict[str, Any]:
    """Single dispatch path shared by the HTTP and stdio transports."""
    params = params or {}

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })

    if method in ("tools/list", "listTools"):
        return _result(req_id, {"tools": registry.list_mcp()})

    if method in ("tools/call", "callTool"):
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return _error(req_id, -32602, "Missing required parameter 'name'.")
        with obs.span(f"mcp:tools/call:{name}", kind="mcp", input=arguments) as sp:
            outcome = registry.call(name, arguments)
            sp.set_output(outcome)
        if not outcome["ok"]:
            # MCP reports tool failures in-band so the calling agent can recover.
            return _result(req_id, {
                "isError": True,
                "content": [{"type": "text", "text": outcome["error"]}],
            })
        return _result(req_id, {
            "isError": False,
            "content": [{"type": "text", "text": _as_text(outcome["result"])}],
            "structuredContent": outcome["result"],
        })

    if method == "ping":
        return _result(req_id, {})

    return _error(req_id, -32601, f"Method not found: {method}")


def _as_text(value: Any) -> str:
    import json
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, default=str)
    except Exception:
        return str(value)


# ------------------------------------------------------------------------------
# HTTP transport
# ------------------------------------------------------------------------------
@router.post("")
@router.post("/")
def mcp_rpc(request: JsonRpcRequest):
    """JSON-RPC 2.0 endpoint implementing initialize / tools.list / tools.call."""
    return dispatch(request.method, request.params, request.id)


@router.get("/tools")
def list_tools():
    """Convenience discovery view (same data as the tools/list RPC)."""
    return {"protocolVersion": PROTOCOL_VERSION, "serverInfo": SERVER_INFO,
            "tools": registry.list_mcp()}


# ------------------------------------------------------------------------------
# stdio transport
# ------------------------------------------------------------------------------
def serve_stdio() -> None:
    """Runs the same registry over MCP stdio for external hosts."""
    import json
    import sys

    logger.info("MCP stdio server started. Awaiting JSON-RPC messages on stdin.")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(_error(None, -32700, "Parse error")) + "\n")
            sys.stdout.flush()
            continue
        response = dispatch(message.get("method", ""), message.get("params", {}), message.get("id"))
        if message.get("id") is not None:  # notifications expect no response
            sys.stdout.write(json.dumps(response, default=str) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    serve_stdio()
