"""
Invoice Audit Workflow
Assembles and executes the LangGraph workflow across:
Extractor -> Translator -> Parser -> Validator -> Business Validation -> Reporter -> Indexing.

Two agentic frameworks meet in this graph. The extractor, parser, data-validation
and reporting steps are LangGraph nodes; translation and business validation are
Google ADK agents reached over the Agent-to-Agent protocol, so the graph never
imports them. Indexing is handed to the agentic RAG package.

Graph state is checkpointed to the PostgreSQL `langgraph` schema so a paused
run can resume; falls back to a plain sequential executor when LangGraph or the
checkpointer backend is unavailable.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from .state import InvoiceState
from .nodes.extractor import extractor_node
from .nodes.translator import translator_node
from .nodes.parser import parser_node
from .nodes.validator import validator_node
from .nodes.reporter import reporter_node
from ..rag.pipeline import indexing_node
from ..a2a.client import a2a_client
from ..config_loader import load_rules
from ..utils import observability as obs
from ..utils.risk_scoring import compute_risk
from ..utils.db import audit_db

logger = logging.getLogger("workflow")

TRANSLATION_AGENT = "translation-agent"
BUSINESS_VALIDATION_AGENT = "business-validation-agent"


def translation_node(state: InvoiceState) -> InvoiceState:
    """Delegates translation to the Google ADK Translation Agent over A2A.

    Falls back to the in-graph translator if the remote agent cannot be reached,
    so a framework or network problem degrades quality rather than halting the audit.
    """
    if state.get("skipped"):
        return state

    raw = state.get("raw_extracted_text") or ""
    if not raw.strip():
        return translator_node(state)

    with obs.span("node:translation", kind="agent",
                  input={"characters": len(raw), "delegate": TRANSLATION_AGENT}) as sp:
        result = a2a_client.try_send(
            TRANSLATION_AGENT, "translate_invoice", {"text": raw},
            context_id=state.get("thread_id"),
        )
        if not result or not result.get("translated_text"):
            sp.set_output({"delegated": False, "reason": "a2a_unavailable"})
            return translator_node(state)

        state["source_language"] = result.get("source_language") or "unknown"
        state["language_name"] = result.get("language_name") or "Unknown"
        state["translated_text"] = result["translated_text"]
        state["translation_confidence"] = float(result.get("translation_confidence") or 0.0)
        sp.set_output({
            "delegated": True, "executor": result.get("executor"),
            "source_language": state["source_language"],
            "translation_confidence": state["translation_confidence"],
            "cached": result.get("cached", False),
        })
    return state


def business_validation_node(state: InvoiceState) -> InvoiceState:
    """Delegates ERP cross-verification to the Google ADK Business Validation Agent.

    The agent reaches the ERP only through the mock-erp HTTP service. Discrepancies
    it finds are merged into the state, de-duplicated against whatever the in-graph
    validator already recorded for the same field.
    """
    if state.get("skipped"):
        return state

    invoice = {k: state.get(k) for k in (
        "invoice_number", "invoice_date", "vendor_id", "vendor_name",
        "po_number", "currency", "subtotal", "tax_amount", "total_amount")}

    with obs.span("node:business_validation", kind="agent",
                  input={"po_number": invoice.get("po_number"), "delegate": BUSINESS_VALIDATION_AGENT}) as sp:
        result = a2a_client.try_send(
            BUSINESS_VALIDATION_AGENT, "validate_against_erp",
            {"invoice": invoice, "line_items": state.get("line_items") or []},
            context_id=state.get("thread_id"),
        )
        if result is None:
            sp.set_output({"delegated": False, "reason": "a2a_unavailable"})
            return state

        existing: List[Dict[str, Any]] = state.get("discrepancies") or []
        seen = {(d.get("field_name"), str(d.get("invoice_value"))) for d in existing}
        added = [d for d in result.get("discrepancies", [])
                 if (d.get("field_name"), str(d.get("invoice_value"))) not in seen]

        state["discrepancies"] = existing + added
        state["business_validation_passed"] = bool(result.get("passed")) and \
            state.get("business_validation_passed", True)
        sp.set_output({"delegated": True, "executor": result.get("executor"),
                       "discrepancies_added": len(added),
                       "blocking": result.get("blocking_count", 0)})
    return state


def risk_gate_node(state: InvoiceState) -> InvoiceState:
    """Scores validation results and decides auto-approval vs. human review.
    Auto-approved invoices continue to indexing; others are held (no indexing)
    until a human approves them via the dashboard."""
    if state.get("skipped"):
        return state

    rules = load_rules()
    score, review_status, reasons = compute_risk(state, rules)
    state["risk_score"] = score
    state["review_status"] = review_status

    invoice_id = state.get("invoice_id")
    if invoice_id:
        try:
            audit_db.update_review_status(invoice_id, review_status, risk_score=score)
        except Exception as e:
            logger.error(f"Could not persist review status for {invoice_id}: {e}")

    logger.info(
        f"Risk gate: score={score} status={review_status} "
        f"({'AUTO-INDEX' if review_status == 'auto_approved' else 'HELD FOR HUMAN REVIEW'}). "
        f"Reasons: {'; '.join(reasons)}"
    )
    return state

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://auditor:auditor_secret@postgres:5432/invoice_db")

_checkpointer = None

def get_checkpointer():
    """Returns a persistent PostgresSaver writing to the `langgraph` schema, or None."""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    try:
        from psycopg_pool import ConnectionPool
        from langgraph.checkpoint.postgres import PostgresSaver

        # Checkpoint tables live in the langgraph schema (created by init.sql).
        pool = ConnectionPool(
            conninfo=DATABASE_URL,
            max_size=5,
            kwargs={"autocommit": True, "options": "-c search_path=langgraph"},
        )
        saver = PostgresSaver(pool)
        saver.setup()
        _checkpointer = saver
        logger.info("LangGraph PostgresSaver checkpointer initialized (schema: langgraph).")
    except Exception as e:
        logger.warning(f"PostgreSQL checkpointer unavailable ({e}). Graph will run without persistence.")
        _checkpointer = None
    return _checkpointer

def build_workflow():
    try:
        from langgraph.graph import StateGraph, START, END

        graph = StateGraph(InvoiceState)

        graph.add_node("extractor", extractor_node)
        graph.add_node("translator", translation_node)
        graph.add_node("parser", parser_node)
        graph.add_node("validator", validator_node)
        graph.add_node("business_validation", business_validation_node)
        graph.add_node("reporter", reporter_node)
        graph.add_node("risk_gate", risk_gate_node)
        graph.add_node("indexing", indexing_node)

        # Edges
        graph.add_edge(START, "extractor")
        graph.add_edge("extractor", "translator")
        graph.add_edge("translator", "parser")
        graph.add_edge("parser", "validator")
        graph.add_edge("validator", "business_validation")
        graph.add_edge("business_validation", "reporter")
        graph.add_edge("reporter", "risk_gate")

        # Only auto-approved invoices proceed to vector-store indexing; anything
        # held for human review ends here and is indexed later upon approval.
        def _route_after_gate(state: InvoiceState) -> str:
            return "indexing" if state.get("review_status") == "auto_approved" else END

        graph.add_conditional_edges("risk_gate", _route_after_gate, {"indexing": "indexing", END: END})
        graph.add_edge("indexing", END)

        checkpointer = get_checkpointer()
        app = graph.compile(checkpointer=checkpointer)
        logger.info(
            "LangGraph workflow compiled successfully with StateGraph "
            f"({'checkpointed' if checkpointer else 'no checkpointer'})."
        )
        return app
    except ImportError:
        logger.warning("langgraph library not installed in current environment. Using pipeline executor.")
        return None

_compiled_app = None

def get_app():
    global _compiled_app
    if _compiled_app is None:
        _compiled_app = build_workflow()
    return _compiled_app

def run_invoice_audit_pipeline(file_path: str) -> InvoiceState:
    """Executes the full audit pipeline for a given invoice file."""
    # Stable per-file thread id links audit rows to their LangGraph checkpoint.
    thread_id = f"invoice-{Path(file_path).stem}"
    initial_state: InvoiceState = {
        "file_path": file_path,
        "file_checksum": "",
        "metadata": {},
        "skipped": False,
        "skip_reason": None,
        "extraction_method": "",
        "raw_extracted_text": "",
        "source_language": "en",
        "language_name": "English",
        "translated_text": "",
        "translation_confidence": 1.0,
        "invoice_number": None,
        "invoice_date": None,
        "vendor_id": None,
        "vendor_name": None,
        "po_number": None,
        "currency": None,
        "subtotal": None,
        "tax_amount": None,
        "total_amount": None,
        "line_items": [],
        "extracted_raw": {},
        "data_validation_passed": False,
        "data_validation_errors": [],
        "business_validation_passed": False,
        "discrepancies": [],
        "validation_status": "pending",
        "recommendation": "review",
        "risk_score": 0.0,
        "review_status": "pending_review",
        "report_json_path": None,
        "report_html_path": None,
        "invoice_id": None,
        "thread_id": thread_id,
        "rag_indexed": False,
        "error": None
    }

    with obs.trace("invoice.audit", session_id=thread_id,
                   input={"file": Path(file_path).name},
                   metadata={"thread_id": thread_id}, tags=["invoice-audit"]) as tr:
        app = get_app()
        final_state: Optional[InvoiceState] = None

        if app:
            try:
                config = {"configurable": {"thread_id": thread_id}}
                final_state = app.invoke(initial_state, config=config)
            except Exception as e:
                logger.error(f"LangGraph execution error: {e}. Executing sequential pipeline.")

        if final_state is None:
            final_state = _run_sequential(initial_state)

        tr.set_output({
            "invoice_id": final_state.get("invoice_id"),
            "skipped": final_state.get("skipped"),
            "validation_status": final_state.get("validation_status"),
            "recommendation": final_state.get("recommendation"),
            "risk_score": final_state.get("risk_score"),
            "review_status": final_state.get("review_status"),
            "discrepancies": len(final_state.get("discrepancies") or []),
            "rag_indexed": final_state.get("rag_indexed"),
        })
        return final_state


def _run_sequential(state: InvoiceState) -> InvoiceState:
    """Same order as the graph, used when LangGraph is unavailable."""
    s = extractor_node(state)
    if s.get("skipped"):
        return s

    s = translation_node(s)
    s = parser_node(s)
    s = validator_node(s)
    s = business_validation_node(s)
    s = reporter_node(s)
    s = risk_gate_node(s)
    # Gate indexing: only index automatically when the risk gate cleared it.
    if s.get("review_status") == "auto_approved":
        s = indexing_node(s)
    return s
