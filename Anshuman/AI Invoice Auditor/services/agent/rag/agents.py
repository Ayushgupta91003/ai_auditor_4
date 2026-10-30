"""
Agentic RAG — agent roles
=========================
Five agents, each owning exactly one tool and one decision. None of them import
a tool directly: every capability is discovered and invoked through MCP, so the
agent is a policy and the tool is the implementation.

  Indexing Agent      parses and indexes invoice documents in the vector DB
  Retrieval Agent     turns a query into an embedding and searches
  Augmentation Agent  reranks chunks and assembles the context window
  Generation Agent    produces the contextual answer through LiteLLM
  Reflection Agent    scores the answer on the RAG Triad and decides retry vs. return
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..mcp_server.client import mcp_client, MCPToolError
from ..utils import observability as obs
from ..utils.db import audit_db
from ..utils.guardrails import guardrails
from .state import RAGState

logger = logging.getLogger("rag.agents")


# ==============================================================================
# Indexing Agent
# ==============================================================================
def build_documents(record: Dict[str, Any]) -> List[Dict[str, str]]:
    """Assembles the indexable text for one invoice from its audit record.

    Everything indexed here already exists in PostgreSQL, which is why losing the
    Qdrant volume is a rebuild rather than data loss.
    """
    documents: List[Dict[str, str]] = []

    raw = record.get("raw_extracted_text") or ""
    translated = record.get("translated_text") or ""
    if raw:
        documents.append({"doc_type": "invoice_text", "text": raw})
    if translated and translated.strip() != raw.strip():
        documents.append({"doc_type": "invoice_translation", "text": translated})

    summary = _summary_text(record)
    if summary:
        documents.append({"doc_type": "audit_summary", "text": summary})

    report = _report_text(record)
    if report:
        documents.append({"doc_type": "audit_report", "text": report})

    return documents


def _summary_text(record: Dict[str, Any]) -> str:
    """A dense, natural-language restatement of the structured audit outcome.

    Without this, questions like "which invoices were rejected?" have nothing to
    match against, because the raw invoice text never contains the verdict.
    """
    lines = [
        f"Invoice {record.get('invoice_number') or 'unknown'} dated {record.get('invoice_date') or 'unknown'}.",
        f"Vendor: {record.get('vendor_name') or 'unknown'} (id {record.get('vendor_id') or 'unknown'}).",
        f"Purchase order: {record.get('po_number') or 'none'}.",
        f"Total amount: {record.get('total_amount')} {record.get('currency') or ''}.".strip(),
        f"Source language: {record.get('source_language') or 'en'}; "
        f"translation confidence: {record.get('translation_confidence')}.",
        f"Validation status: {record.get('validation_status')}; "
        f"recommendation: {record.get('recommendation')}; "
        f"review status: {record.get('review_status')}; risk score: {record.get('risk_score')}.",
    ]

    for item in record.get("line_items") or []:
        lines.append(
            f"Line {item.get('line_number')}: {item.get('item_code')} {item.get('description')} "
            f"quantity {item.get('quantity')} at unit price {item.get('unit_price')} "
            f"= {item.get('line_total')}."
        )

    discrepancies = record.get("discrepancies") or []
    if discrepancies:
        lines.append(f"{len(discrepancies)} discrepancies were found against the ERP:")
        for d in discrepancies:
            lines.append(
                f"- {d.get('severity')} on {d.get('field_name')}: invoice value {d.get('invoice_value')} "
                f"vs ERP value {d.get('erp_value')} ({d.get('deviation_pct')}% deviation)."
            )
    else:
        lines.append("No discrepancies were found against the ERP.")

    errors = record.get("data_validation_errors") or []
    if errors:
        lines.append("Missing or inconsistent fields: " + "; ".join(str(e) for e in errors) + ".")

    return "\n".join(lines)


def _report_text(record: Dict[str, Any]) -> str:
    path = record.get("report_json_path")
    if not path:
        return ""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return json.dumps(data, indent=2, default=str)
    except Exception:
        return ""


def indexing_agent(invoice_id: str, record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Chunks, embeds and writes one invoice's text to the vector DB."""
    with obs.span("agent:indexing", kind="agent", input={"invoice_id": invoice_id}) as sp:
        record = record or audit_db.get_invoice_details(invoice_id) or {}
        documents = build_documents(record)
        if not documents:
            outcome = {"invoice_id": invoice_id, "indexed": False, "chunks_indexed": 0,
                       "reason": "no_text_available"}
            sp.set_output(outcome)
            return outcome

        metadata = {
            "invoice_number": record.get("invoice_number"),
            "vendor_name": record.get("vendor_name"),
            "po_number": record.get("po_number"),
            "currency": record.get("currency"),
            "review_status": record.get("review_status"),
            "recommendation": record.get("recommendation"),
        }
        outcome = mcp_client.call("vector_indexer", invoice_id=invoice_id,
                                  documents=documents, metadata=_clean(metadata))
        sp.set_output(outcome)
        return outcome


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (str(v) if v is not None else "") for k, v in payload.items()}


# ==============================================================================
# Retrieval Agent
# ==============================================================================
def retrieval_agent(state: RAGState) -> RAGState:
    """Embeds the (possibly refined) query and performs similarity search."""
    query = state.get("search_query") or state["query"]
    with obs.span("agent:retrieval", kind="agent",
                  input={"query": query, "invoice_id": state.get("invoice_id"),
                         "attempt": state.get("attempt", 1)}) as sp:
        try:
            result = mcp_client.call("semantic_retriever", query=query,
                                     invoice_id=state.get("invoice_id"))
            state["retrieved_chunks"] = result.get("chunks", [])
        except MCPToolError as e:
            logger.error(f"Retrieval failed: {e}")
            state["retrieved_chunks"] = []
            state["error"] = str(e)
        state["search_query"] = query
        sp.set_output({"retrieved": len(state["retrieved_chunks"])})
    return state


# ==============================================================================
# Augmentation Agent
# ==============================================================================
def augmentation_agent(state: RAGState) -> RAGState:
    """Reranks the candidates by relevance and assembles the context window."""
    with obs.span("agent:augmentation", kind="agent",
                  input={"candidates": len(state.get("retrieved_chunks") or [])}) as sp:
        chunks = state.get("retrieved_chunks") or []
        if not chunks:
            state["ranked_chunks"], state["context"] = [], ""
            sp.set_output({"ranked": 0})
            return state
        result = mcp_client.call("chunk_ranker",
                                 query=state.get("search_query") or state["query"],
                                 chunks=chunks)
        state["ranked_chunks"] = result.get("ranked_chunks", [])
        state["context"] = result.get("context", "")
        sp.set_output({"ranked": len(state["ranked_chunks"]),
                       "context_characters": result.get("context_characters", 0)})
    return state


# ==============================================================================
# Generation Agent
# ==============================================================================
def generation_agent(state: RAGState) -> RAGState:
    """Answers the auditor's original question from the assembled context."""
    with obs.span("agent:generation", kind="agent",
                  input={"query": state["query"], "context_characters": len(state.get("context") or "")}) as sp:
        context = state.get("context") or ""
        if not context.strip():
            state["answer"] = ("No indexed invoice content matched that question. "
                               "Process or approve the relevant invoice first, then ask again.")
            state["answer_cached"] = False
            state["guardrail"] = {"allowed": True, "findings": []}
            sp.set_output({"answer": state["answer"], "context": "empty"})
            return state

        # Always generate against the auditor's real question, never the refined
        # search string — refinement exists to improve retrieval, not to change
        # what was asked.
        result = mcp_client.call("response_synthesizer", query=state["query"], context=context)
        state["answer"] = result.get("answer", "")
        state["answer_cached"] = bool(result.get("cached"))
        state["guardrail"] = {"allowed": result.get("guardrail_allowed", True),
                              "findings": result.get("guardrail_findings", [])}
        sp.set_output({"cached": state["answer_cached"],
                       "guardrail_allowed": state["guardrail"]["allowed"]})
    return state


# ==============================================================================
# Reflection Agent
# ==============================================================================
def reflection_agent(state: RAGState) -> RAGState:
    """Scores the RAG Triad and records this attempt in the run history."""
    with obs.span("agent:reflection", kind="agent", input={"attempt": state.get("attempt", 1)}) as sp:
        metrics = mcp_client.call("rag_evaluator", query=state["query"],
                                  context=state.get("context") or "",
                                  answer=state.get("answer") or "")
        state.update({
            "context_relevance": metrics.get("context_relevance", 0.0),
            "groundedness": metrics.get("groundedness", 0.0),
            "answer_relevance": metrics.get("answer_relevance", 0.0),
            "average_score": metrics.get("average_score", 0.0),
            "threshold": metrics.get("threshold", 0.70),
            "passed": bool(metrics.get("passed")),
            "critique": metrics.get("critique", ""),
        })

        attempt_record = {
            "attempt": state.get("attempt", 1),
            "search_query": state.get("search_query"),
            "retrieved": len(state.get("retrieved_chunks") or []),
            "ranked": len(state.get("ranked_chunks") or []),
            "answer": state.get("answer"),
            "context_relevance": state["context_relevance"],
            "groundedness": state["groundedness"],
            "answer_relevance": state["answer_relevance"],
            "average_score": state["average_score"],
            "passed": state["passed"],
            "critique": state["critique"],
        }
        state.setdefault("history", []).append(attempt_record)

        best = state.get("best_attempt")
        if best is None or attempt_record["average_score"] > best["average_score"]:
            state["best_attempt"] = attempt_record

        sp.set_output({k: attempt_record[k] for k in
                       ("average_score", "passed", "context_relevance", "groundedness", "answer_relevance")})
    return state


def refine_agent(state: RAGState) -> RAGState:
    """Reflection Agent's recovery step: rewrite the search query and retry."""
    with obs.span("agent:reflection:refine", kind="agent",
                  input={"attempt": state.get("attempt", 1), "critique": state.get("critique")}) as sp:
        result = mcp_client.try_call(
            "query_refiner", default={"refined_query": state.get("search_query") or state["query"]},
            query=state.get("search_query") or state["query"], critique=state.get("critique", ""),
        )
        state["search_query"] = result.get("refined_query") or state["query"]
        state["attempt"] = state.get("attempt", 1) + 1
        sp.set_output({"next_attempt": state["attempt"], "refined_query": state["search_query"]})
    return state


def finalize(state: RAGState) -> RAGState:
    """Returns the passing answer, or the best-scoring attempt once retries run out."""
    if not state.get("passed") and state.get("best_attempt"):
        best = state["best_attempt"]
        state.update({
            "answer": best["answer"],
            "context_relevance": best["context_relevance"],
            "groundedness": best["groundedness"],
            "answer_relevance": best["answer_relevance"],
            "average_score": best["average_score"],
            "critique": best["critique"],
        })

    if not state.get("passed"):
        state["answer"] = (
            f"{state.get('answer', '')}\n\n_Quality gate not met: the RAG Triad average score was "
            f"{state.get('average_score', 0.0)} against a required {state.get('threshold', 0.7)} after "
            f"{len(state.get('history', []))} attempt(s). Treat this answer as unverified and check the "
            f"invoice report directly._"
        ).strip()

    scan = guardrails.scan_answer(state.get("answer", ""), context=state.get("context", ""),
                                  query=state.get("query", ""))
    state["answer"] = scan.text
    state["blocked"] = not scan.allowed
    state["guardrail"] = {"allowed": scan.allowed, "findings": scan.findings,
                          "blocked_reason": scan.blocked_reason}
    return state
