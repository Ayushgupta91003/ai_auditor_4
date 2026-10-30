"""Model Context Protocol server and client for the AI Invoice Auditor."""

from .client import MCPClient, MCPToolError, mcp_client
from .server import router as mcp_router, dispatch, PROTOCOL_VERSION, SERVER_INFO

__all__ = [
    "MCPClient", "MCPToolError", "mcp_client",
    "mcp_router", "dispatch", "PROTOCOL_VERSION", "SERVER_INFO",
]
