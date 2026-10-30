"""
Tool layer for the AI Invoice Auditor.

Importing this package registers every tool with the shared `registry`, which is
what the MCP server advertises and what the LangGraph and Google ADK agents call
through. Import order matters only in that both modules must be imported for the
registry to be complete.
"""

from .registry import registry, Tool, ToolRegistry
from . import invoice_tools  # noqa: F401  (registers the six invoice-audit tools)
from . import rag_tools      # noqa: F401  (registers the five RAG tools)

__all__ = ["registry", "Tool", "ToolRegistry"]
