"""
Agentic RAG — LangGraph pipeline
================================
Wires the five RAG agents into a graph with the quality gate the brief requires:

    retrieval -> augmentation -> generation -> reflection
                       ^                           |
                       |     avg <= 0.70 and       |
                       +----- attempts < 3 --------+  (refine the search query)

If the RAG Triad average exceeds the threshold the answer is returned to the
auditor. Otherwise the Reflection Agent refines the query and retrieval runs
again, up to `max_retries` attempts; after that the best-scoring attempt is
returned, explicitly labelled as not having met the gate.

Falls back to a plain Python loop when LangGraph is unavailable, so the quality
gate is enforced either way.
"""

import logging
from typing import Any, Dict, List, Optional

from ..config_loader import load_rules
from ..utils import observability as obs
from ..utils.db import audit_db
from ..utils.guardrails import guardrails
from ..utils.vector_store import vector_store
from .agents import (
    augmentation_agent, finalize, generation_agent, indexing_agent,
    reflection_agent, refine_agent, retrieval_agent,
)
from .state import RAGState

logger = logging.getLogger("rag.pipeline")

_compiled = None


def _rag_cfg() -> Dict[str, Any]:
    return (load_rules() or {}).get("rag", {}) or {}


def _should_retry(state: RAGState) -> str:
    if state.get("passed"):
        return "finalize"
    if state.get("attempt", 1) >= int(state.get("max_retries", 3)):
        return "finalize"
    if not (state.get("retrieved_chunks") or []):
        # Nothing is indexed for this filter; refining the wording cannot help.
        return "finalize"
    return "refine"


def build_rag_graph():
    try:
        from langgraph.graph import StateGraph, START, END

        graph = StateGraph(RAGState)
        graph.add_node("retrieval", retrieval_agent)
        graph.add_node("augmentation", augmentation_agent)
        graph.add_node("generation", generation_agent)
        graph.add_node("reflection", reflection_agent)
        graph.add_node("refine", refine_agent)
        graph.add_node("finalize", finalize)

        graph.add_edge(START, "retrieval")
        graph.add_edge("retrieval", "augmentation")
        graph.add_edge("augmentation", "generation")
        graph.add_edge("generation", "reflection")
        graph.add_conditional_edges("reflection", _should_retry,
                                    {"refine": "refine", "finalize": "finalize"})
        graph.add_edge("refine", "retrieval")
        graph.add_edge("finalize", END)

        app = graph.compile()
        logger.info("Agentic RAG graph compiled (retrieval -> augmentation -> generation -> reflection).")
        return app
    except ImportError:
        logger.warning("langgraph unavailable. Agentic RAG will run as a sequential loop.")
        return None


def get_rag_app():
    global _compiled
    if _compiled is None:
        _compiled = build_rag_graph()
    return _compiled


def _run_sequential(state: RAGState) -> RAGState:
    while True:
        state = retrieval_agent(state)
        state = augmentation_agent(state)
        state = generation_agent(state)
        state = reflection_agent(state)
        if _should_retry(state) == "finalize":
            return finalize(state)
        state = refine_agent(state)


# ==============================================================================
# Public entry points
# ==============================================================================
def query_rag_with_triad(query: str, invoice_id: Optional[str] = None,
                         max_retries: Optional[int] = None,
                         user: str = "auditor") -> Dict[str, Any]:
    """Answers an auditor question through the five-agent RAG pipeline."""
    cfg = _rag_cfg()
    retries = int(max_retries or cfg.get("max_retries", 3))

    with obs.trace("rag.query", user_id=user, input={"query": query, "invoice_id": invoice_id},
                   metadata={"max_retries": retries}, tags=["rag"]) as tr:
        gate = guardrails.scan_user_query(query, user=user)
        if not gate.allowed:
            blocked = {
                "query": query, "answer": gate.text, "blocked": True,
                "blocked_reason": gate.blocked_reason, "guardrail": gate.as_dict(),
                "triad": {"context_relevance": 0.0, "groundedness": 0.0,
                          "answer_relevance": 0.0, "average_score": 0.0,
                          "threshold": float(cfg.get("triad_pass_threshold", 0.70)), "passed": False},
                "attempts": 0, "history": [], "sources": [],
            }
            tr.set_output(blocked)
            return blocked

        state: RAGState = {
            "query": gate.text, "search_query": gate.text, "invoice_id": invoice_id,
            "max_retries": retries, "attempt": 1, "history": [], "best_attempt": None,
            "retrieved_chunks": [], "ranked_chunks": [], "context": "",
            "answer": "", "answer_cached": False, "blocked": False, "error": None,
        }

        app = get_rag_app()
        if app is not None:
            try:
                state = app.invoke(state, config={"recursion_limit": 4 * retries + 10})
            except Exception as e:
                logger.error(f"RAG graph execution failed ({e}). Running the sequential loop.")
                state = _run_sequential(state)
        else:
            state = _run_sequential(state)

        response = {
            "query": query,
            "search_query": state.get("search_query"),
            "invoice_id": invoice_id,
            "answer": state.get("answer", ""),
            "blocked": state.get("blocked", False),
            "cached": state.get("answer_cached", False),
            "triad": {
                "context_relevance": state.get("context_relevance", 0.0),
                "groundedness": state.get("groundedness", 0.0),
                "answer_relevance": state.get("answer_relevance", 0.0),
                "average_score": state.get("average_score", 0.0),
                "threshold": state.get("threshold", float(cfg.get("triad_pass_threshold", 0.70))),
                "passed": state.get("passed", False),
                "critique": state.get("critique", ""),
            },
            "attempts": len(state.get("history", [])),
            "retries_used": max(0, len(state.get("history", [])) - 1),
            "history": state.get("history", []),
            "guardrail": state.get("guardrail", {}),
            "sources": [{
                "invoice_id": c.get("invoice_id"),
                "invoice_number": c.get("invoice_number"),
                "doc_type": c.get("doc_type"),
                "score": c.get("rerank_score", c.get("score")),
            } for c in state.get("ranked_chunks", [])],
        }

        triad = response["triad"]
        for metric in ("context_relevance", "groundedness", "answer_relevance", "average_score"):
            tr.score(f"rag_triad.{metric}", triad[metric], comment=triad.get("critique", ""))
        tr.set_output(response)
        return response


def indexing_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Graph node: indexes the invoice that has just been audited.

    Kept signature-compatible with the workflow so the Indexing Agent slots into
    the audit pipeline exactly where the old single-function indexer sat.
    """
    if state.get("skipped"):
        return state

    invoice_id = state.get("invoice_id")
    if not invoice_id:
        logger.warning("Indexing skipped: the invoice has no audit id.")
        state["rag_indexed"] = False
        return state

    record = {**state, "invoice_id": invoice_id}
    try:
        outcome = indexing_agent(invoice_id, record=record)
        state["rag_indexed"] = bool(outcome.get("indexed"))
        logger.info(f"Indexed invoice {invoice_id}: {outcome.get('chunks_indexed', 0)} chunks.")
    except Exception as e:
        logger.error(f"Indexing failed for {invoice_id}: {e}")
        state["rag_indexed"] = False
    return state


def index_invoice(invoice_id: str) -> Dict[str, Any]:
    """Indexes a single invoice straight from its PostgreSQL audit record."""
    return indexing_agent(invoice_id)


def rebuild_index(review_statuses: Optional[List[str]] = None) -> Dict[str, Any]:
    """Rebuilds the entire vector index from PostgreSQL.

    This is the operation that makes Qdrant a derived store: destroy its volume,
    run this, and the RAG index is whole again without re-reading one PDF.
    """
    allowed = set(review_statuses or ["auto_approved", "approved"])
    with obs.trace("rag.rebuild_index", input={"review_statuses": sorted(allowed)}) as tr:
        indexed, skipped, chunks = 0, 0, 0
        for summary in audit_db.list_invoices():
            invoice_id = summary.get("invoice_id") or summary.get("id")
            if not invoice_id:
                continue
            if summary.get("review_status") not in allowed:
                skipped += 1
                continue
            outcome = indexing_agent(str(invoice_id))
            if outcome.get("indexed"):
                indexed += 1
                chunks += int(outcome.get("chunks_indexed", 0))
            else:
                skipped += 1
        result = {"invoices_indexed": indexed, "invoices_skipped": skipped,
                  "chunks_written": chunks, "store": vector_store.stats()}
        tr.set_output(result)
        logger.info(f"Vector index rebuilt from PostgreSQL: {result}")
        return result
