"""
Tool Registry
=============
Every capability an agent can use is declared here as a `Tool` with a JSON
Schema, so it can be *discovered* rather than hard-wired. The registry is the
backing store for the MCP server (`services/agent/mcp_server`), which exposes
exactly these definitions over the Model Context Protocol.

Invoking a tool through the registry gives three things for free:
  * a LangFuse span with the tool's input, output and latency,
  * RAI guardrail enforcement declared per tool,
  * uniform error shaping, so a failing tool returns a result instead of
    collapsing the agent that called it.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..utils import observability as obs

logger = logging.getLogger("tools")


@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Any]
    agent: str = ""                       # owning agent role
    guardrails: List[str] = field(default_factory=list)
    read_only: bool = True

    def to_mcp(self) -> Dict[str, Any]:
        """MCP `tools/list` entry."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "owningAgent": self.agent,
                "readOnlyHint": self.read_only,
                "guardrails": self.guardrails,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool
        return tool

    def tool(self, name: str, description: str, input_schema: Dict[str, Any],
             agent: str = "", guardrails: Optional[List[str]] = None, read_only: bool = True):
        """Decorator registering the wrapped function as a discoverable tool."""
        def decorator(fn: Callable[..., Any]):
            self.register(Tool(
                name=name, description=description, input_schema=input_schema,
                handler=fn, agent=agent, guardrails=guardrails or [], read_only=read_only,
            ))
            return fn
        return decorator

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool '{name}'. Known tools: {sorted(self._tools)}")
        return self._tools[name]

    def list(self) -> List[Tool]:
        return [self._tools[n] for n in sorted(self._tools)]

    def list_mcp(self) -> List[Dict[str, Any]]:
        return [t.to_mcp() for t in self.list()]

    def call(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Invokes a tool. Always returns {ok, tool, result|error}."""
        arguments = arguments or {}
        try:
            tool = self.get(name)
        except KeyError as e:
            return {"ok": False, "tool": name, "error": str(e)}

        with obs.span(f"tool:{name}", kind="tool", input=arguments,
                      metadata={"agent": tool.agent, "guardrails": tool.guardrails}) as sp:
            try:
                result = tool.handler(**arguments)
                payload = {"ok": True, "tool": name, "result": result}
            except TypeError as e:
                payload = {"ok": False, "tool": name, "error": f"Invalid arguments: {e}"}
            except Exception as e:
                logger.exception(f"Tool '{name}' failed.")
                payload = {"ok": False, "tool": name, "error": f"{type(e).__name__}: {e}"}
            sp.set_output(payload)
            return payload


registry = ToolRegistry()
