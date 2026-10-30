"""
LangGraph agents published over A2A
===================================
The four audit roles implemented with LangGraph, plus the RAG orchestrator, are
registered here so they appear in the same discovery directory as the Google ADK
agents and can be invoked with the same envelope.

This is what makes the two frameworks interoperable: a caller reads
`/a2a/agents`, picks a skill, and sends a message. Which framework answers is an
implementation detail of the agent, not of the caller.
"""

import logging
from typing import Any, Dict

from ..mcp_server.client import mcp_client
from .models import AgentCapabilities, AgentCard, AgentSkill
from .registry import A2AAgent, registry

logger = logging.getLogger("a2a.langgraph_agents")

BASE_URL = "http://agent:8000/a2a"


def _card(name: str, description: str, agent_id: str, skills) -> AgentCard:
    return AgentCard(
        name=name, description=description, url=f"{BASE_URL}/{agent_id}",
        capabilities=AgentCapabilities(streaming=False, stateTransitionHistory=True),
        framework="langgraph", skills=skills,
    )


# ------------------------------------------------------------------------------
# Invoice-Monitor Agent
# ------------------------------------------------------------------------------
def _monitor(payload: Dict[str, Any]) -> Dict[str, Any]:
    return mcp_client.call("invoice_watcher",
                           directory=payload.get("directory"),
                           include_audited=payload.get("include_audited", False))


registry.register(A2AAgent(
    agent_id="invoice-monitor-agent",
    card=_card(
        "Invoice-Monitor Agent",
        ("Monitors the mailbox drop directory for invoice attachments, checksums each file and "
         "reports which are new and which are already in the audit trail."),
        "invoice-monitor-agent",
        [AgentSkill(id="detect_invoices", name="Detect incoming invoices",
                    description="Scans the incoming directory and returns detected files with checksums.",
                    tags=["monitoring", "ingestion"])],
    ),
    skills={"detect_invoices": _monitor},
))


# ------------------------------------------------------------------------------
# Extractor Agent
# ------------------------------------------------------------------------------
def _extract(payload: Dict[str, Any]) -> Dict[str, Any]:
    return mcp_client.call("data_harvester", file_path=payload["file_path"])


registry.register(A2AAgent(
    agent_id="extractor-agent",
    card=_card(
        "Extractor Agent",
        ("Extracts raw text from PDF, DOCX and scanned image invoices, using the embedded text "
         "layer where one exists and Tesseract OCR where it does not."),
        "extractor-agent",
        [AgentSkill(id="extract_document", name="Extract invoice text",
                    description="Returns raw extracted text, extraction method and content checksum.",
                    tags=["extraction", "ocr"],
                    examples=['{"file_path": "/app/data/incoming/INV_EN_001.pdf"}'])],
    ),
    skills={"extract_document": _extract},
))


# ------------------------------------------------------------------------------
# Invoice Data Validation Agent
# ------------------------------------------------------------------------------
def _check_completeness(payload: Dict[str, Any]) -> Dict[str, Any]:
    return mcp_client.call("data_completeness_checker",
                           invoice=payload.get("invoice", {}),
                           line_items=payload.get("line_items", []))


registry.register(A2AAgent(
    agent_id="invoice-data-validation-agent",
    card=_card(
        "Invoice Data Validation Agent",
        ("Validates a parsed invoice for completeness, field types, accepted currency and internal "
         "arithmetic consistency against the dynamic rules in rules.yaml."),
        "invoice-data-validation-agent",
        [AgentSkill(id="check_completeness", name="Check invoice completeness",
                    description="Returns missing fields, rule violations and arithmetic inconsistencies.",
                    tags=["validation", "rules"])],
    ),
    skills={"check_completeness": _check_completeness},
))


# ------------------------------------------------------------------------------
# Reporting Agent
# ------------------------------------------------------------------------------
def _report(payload: Dict[str, Any]) -> Dict[str, Any]:
    return mcp_client.call("insight_reporter", state=payload.get("state", payload))


registry.register(A2AAgent(
    agent_id="reporting-agent",
    card=_card(
        "Reporting Agent",
        ("Generates the JSON and HTML audit reports covering discrepancies, missing fields, "
         "translation confidence and the final recommendation, and writes the outcome to PostgreSQL."),
        "reporting-agent",
        [AgentSkill(id="generate_report", name="Generate an audit report",
                    description="Produces machine and human reports and persists the audit outcome.",
                    tags=["reporting", "audit"])],
    ),
    skills={"generate_report": _report},
))


# ------------------------------------------------------------------------------
# RAG orchestrator (Indexing / Retrieval / Augmentation / Generation / Reflection)
# ------------------------------------------------------------------------------
def _ask(payload: Dict[str, Any]) -> Dict[str, Any]:
    from ..rag.pipeline import query_rag_with_triad
    return query_rag_with_triad(payload.get("query", ""),
                                invoice_id=payload.get("invoice_id"),
                                max_retries=payload.get("max_retries"),
                                user=payload.get("user", "a2a"))


def _index(payload: Dict[str, Any]) -> Dict[str, Any]:
    from ..rag.pipeline import index_invoice
    return index_invoice(payload["invoice_id"])


registry.register(A2AAgent(
    agent_id="rag-orchestrator-agent",
    card=_card(
        "RAG Orchestrator Agent",
        ("Runs the five-agent RAG pipeline — indexing, retrieval, augmentation, generation and "
         "reflection — and only returns an answer whose RAG Triad average clears the configured "
         "threshold, retrying with a refined query otherwise."),
        "rag-orchestrator-agent",
        [
            AgentSkill(id="ask", name="Answer a question about processed invoices",
                       description="Runs retrieval, reranking, generation and RAG Triad reflection.",
                       tags=["rag", "qa"],
                       examples=['{"query": "Which invoices have price discrepancies?"}']),
            AgentSkill(id="index_invoice", name="Index one invoice",
                       description="Chunks, embeds and writes an audited invoice into the vector index.",
                       tags=["rag", "indexing"]),
        ],
    ),
    skills={"ask": _ask, "index_invoice": _index},
))
