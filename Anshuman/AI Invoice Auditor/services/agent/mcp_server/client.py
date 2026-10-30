"""
MCP Client
==========
What every agent in this system uses to reach a tool. Agents never import a tool
function: they ask the MCP server what exists, then invoke by name. Swapping a
tool implementation therefore never touches an agent.

Transport is selected by ``MCP_SERVER_URL``:
  unset  -> in-process dispatch against the local MCP server (default; no network
            hop for agents running inside the agent container)
  set    -> JSON-RPC over HTTP, for agents running in another process or container
"""

import os
import json
import logging
import itertools
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mcp.client")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "").strip()
_ids = itertools.count(1)


class MCPToolError(RuntimeError):
    """Raised when a discovered tool reports failure."""


class MCPClient:
    def __init__(self, server_url: Optional[str] = None):
        self.server_url = (server_url if server_url is not None else MCP_SERVER_URL).rstrip("/")
        self._tools: Optional[List[Dict[str, Any]]] = None

    # -- transport -------------------------------------------------------------
    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params or {}}
        if self.server_url:
            import httpx
            resp = httpx.post(f"{self.server_url}/mcp", json=payload, timeout=120)
            resp.raise_for_status()
            message = resp.json()
        else:
            from .server import dispatch
            message = dispatch(method, payload["params"], payload["id"])
        if "error" in message:
            raise MCPToolError(f"MCP error {message['error'].get('code')}: {message['error'].get('message')}")
        return message.get("result", {})

    # -- discovery -------------------------------------------------------------
    def list_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        if self._tools is None or refresh:
            self._tools = self._rpc("tools/list").get("tools", [])
        return self._tools

    def tool_names(self) -> List[str]:
        return [t["name"] for t in self.list_tools()]

    def has_tool(self, name: str) -> bool:
        return name in self.tool_names()

    def describe(self, name: str) -> Dict[str, Any]:
        for tool in self.list_tools():
            if tool["name"] == name:
                return tool
        raise MCPToolError(f"Tool '{name}' is not advertised by the MCP server.")

    # -- invocation ------------------------------------------------------------
    def call(self, name: str, **arguments: Any) -> Any:
        """Invokes a discovered tool and returns its structured result.

        Raises MCPToolError on failure so an agent can decide whether to recover
        or let the workflow surface the error.
        """
        if not self.has_tool(name):
            self.list_tools(refresh=True)
            if not self.has_tool(name):
                raise MCPToolError(f"Tool '{name}' is not advertised by the MCP server.")

        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            message = "".join(c.get("text", "") for c in result.get("content", []))
            raise MCPToolError(f"Tool '{name}' failed: {message}")

        if "structuredContent" in result:
            return result["structuredContent"]
        text = "".join(c.get("text", "") for c in result.get("content", []))
        try:
            return json.loads(text)
        except Exception:
            return text

    def try_call(self, name: str, default: Any = None, **arguments: Any) -> Any:
        """Non-raising variant for optional, best-effort steps."""
        try:
            return self.call(name, **arguments)
        except Exception as e:
            logger.warning(f"MCP tool '{name}' unavailable or failed ({e}). Continuing without it.")
            return default


mcp_client = MCPClient()
