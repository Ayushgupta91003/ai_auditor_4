"""
FastAPI Agent Service
Exposes endpoints for triggering invoice processing, performing agentic RAG
queries with RAG Triad evaluation, reviewing audit results and recording human
feedback.

It also hosts the two interoperability surfaces the solution is built on:
  /mcp   Model Context Protocol  — tool discovery and invocation
  /a2a   Agent-to-Agent protocol — agent discovery and messaging across the
         LangGraph and Google ADK agents
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from contextlib import asynccontextmanager
from .bootstrap import bootstrap, summary as agentic_summary
from .graph.workflow import run_invoice_audit_pipeline
from .rag.pipeline import query_rag_with_triad, indexing_node, index_invoice, rebuild_index
from .graph.nodes.validator import validator_node
from .graph.nodes.reporter import reporter_node
from .a2a.server import router as a2a_router
from .a2a.registry import registry as a2a_registry
from .mcp_server.server import router as mcp_router
from .config_loader import load_rules
from .utils.cache import response_cache
from .utils.risk_scoring import compute_risk
from .utils.db import audit_db
from .utils.vector_store import vector_store
from .utils import observability as obs
from .watcher import get_watchdog

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("agent_api")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
INCOMING_DIR = Path(os.getenv("INCOMING_DIR", str(BASE_DIR / "data" / "incoming")))
MOCK_ERP_URL = os.getenv("MOCK_ERP_URL", "http://mock-erp:8000").rstrip("/")
STRICT_STARTUP = os.getenv("STRICT_STARTUP", "true").strip().lower() not in ("0", "false", "no")


def verify_dependencies() -> Dict[str, Any]:
    """Fails fast when a hard dependency is unreachable.

    Starting in a half-working state is worse than not starting: an agent that
    silently cannot reach the ERP would record clean audits for invoices it never
    actually validated.
    """
    import httpx

    checks: Dict[str, Any] = {}

    checks["postgres"] = {"required": True, "ok": bool(audit_db.use_postgres),
                          "detail": "postgresql" if audit_db.use_postgres else "sqlite_fallback"}
    try:
        resp = httpx.get(f"{MOCK_ERP_URL}/health", timeout=10)
        checks["mock_erp"] = {"required": True, "ok": resp.status_code == 200,
                              "detail": resp.json() if resp.status_code == 200 else resp.text}
    except Exception as e:
        checks["mock_erp"] = {"required": True, "ok": False, "detail": str(e)}

    qdrant = vector_store.health()
    checks["qdrant"] = {"required": False, "ok": qdrant.get("reachable", False), "detail": qdrant}
    redis_health = response_cache.health()
    checks["redis"] = {"required": False, "ok": redis_health.get("reachable", False),
                       "detail": redis_health}

    failed = [name for name, c in checks.items() if c["required"] and not c["ok"]]
    if failed and STRICT_STARTUP:
        raise RuntimeError(
            f"Required dependencies unreachable: {', '.join(failed)}. "
            f"Refusing to start in a broken state. Details: {json.dumps(checks, default=str)}"
        )
    for name, check in checks.items():
        if not check["ok"]:
            logger.warning(f"Dependency '{name}' is degraded: {check['detail']}")
    return checks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify dependencies, bring the agentic surface online, start the watchdog.
    app.state.dependencies = verify_dependencies()
    app.state.agentic = bootstrap()

    poll_sec = float(os.getenv("WATCHDOG_POLL_INTERVAL", "4.0"))
    logger.info(f"Starting autonomous invoice watchdog on {INCOMING_DIR} (interval: {poll_sec}s)...")
    watchdog = get_watchdog(incoming_dir=INCOMING_DIR, poll_interval=poll_sec)
    watchdog.start()
    yield
    # Shutdown: stop watchdog thread cleanly
    logger.info("Shutting down invoice watchdog...")
    watchdog.stop()

app = FastAPI(
    title="AI Invoice Auditor Agent Service",
    description=("Multilingual invoice auditor built on LangGraph and Google ADK, with MCP tool "
                 "discovery, A2A agent interoperability and agentic RAG question answering"),
    version="2.0.0",
    lifespan=lifespan
)

app.include_router(mcp_router)
app.include_router(a2a_router)

# ------------------------------------------------------------------------------
# Pydantic Request/Response Models
# ------------------------------------------------------------------------------
class ProcessRequest(BaseModel):
    file_path: Optional[str] = None
    scan_all: bool = False

class RAGQueryRequest(BaseModel):
    query: str
    invoice_id: Optional[str] = None
    max_retries: int = 3
    user: Optional[str] = "auditor"

class RebuildIndexRequest(BaseModel):
    review_statuses: Optional[List[str]] = None

class FeedbackRequest(BaseModel):
    field_name: str
    original_value: str
    corrected_value: str
    corrected_by: Optional[str] = "Auditor"

class RevalidateRequest(BaseModel):
    corrections: Dict[str, Any] = {}                 # header field -> new value
    line_items: Optional[List[Dict[str, Any]]] = None  # full replacement list (optional)
    reviewed_by: Optional[str] = "Auditor"

class DecisionRequest(BaseModel):
    reviewed_by: Optional[str] = "Auditor"
    notes: Optional[str] = ""

# ------------------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "invoice-auditor-agent",
        "database": "postgresql" if audit_db.use_postgres else "sqlite_fallback",
        "vector_store": vector_store.stats(),
        "cache": response_cache.stats(),
        "observability": obs.status(),
        "agentic": agentic_summary(),
    }

@app.post("/observability/test")
def observability_test():
    """Emits one trace with a nested span, a generation and a score.

    Proves credentials, region URL and SDK wiring in a single call, instead of
    waiting on a real audit run to discover nothing was exported.
    """
    result = obs.emit_test_trace()
    if not result.get("sent"):
        raise HTTPException(status_code=503, detail=result)
    return {"message": "Test trace sent. It should appear in LangFuse within a few seconds.",
            **result}

@app.get("/health/dependencies")
def health_dependencies():
    """Live re-check of every downstream dependency."""
    import httpx
    checks: Dict[str, Any] = {
        "postgres": {"ok": bool(audit_db.use_postgres)},
        "qdrant": vector_store.health(),
        "redis": response_cache.health(),
    }
    try:
        resp = httpx.get(f"{MOCK_ERP_URL}/health", timeout=10)
        checks["mock_erp"] = {"ok": resp.status_code == 200, "detail": resp.json()}
    except Exception as e:
        checks["mock_erp"] = {"ok": False, "detail": str(e)}
    return checks

@app.get("/.well-known/agent.json")
@app.get("/.well-known/agent-card.json")
def primary_agent_card():
    """A2A discovery entry point for the stack's orchestrating agent."""
    bootstrap()
    return a2a_registry.get("rag-orchestrator-agent").card.to_dict()

@app.get("/agents")
def list_agents():
    """Every agent in the stack, which framework implements it, and its skills."""
    bootstrap()
    return {"count": len(a2a_registry.list()), "agents": a2a_registry.directory()}

@app.post("/process")
def process_invoices(req: ProcessRequest):
    """Processes a specific invoice file or scans the entire incoming directory."""
    results = []

    if req.file_path:
        target = Path(req.file_path)
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
        state = run_invoice_audit_pipeline(str(target))
        results.append({
            "file": target.name,
            "skipped": state.get("skipped", False),
            "status": state.get("validation_status"),
            "recommendation": state.get("recommendation"),
            "invoice_id": state.get("invoice_id")
        })
    elif req.scan_all or True:
        # Scan incoming directory
        if not INCOMING_DIR.exists():
            raise HTTPException(status_code=404, detail="Incoming directory does not exist.")
        
        valid_exts = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg"}
        files = [p for p in INCOMING_DIR.iterdir() if p.suffix.lower() in valid_exts]
        
        for f in sorted(files):
            try:
                state = run_invoice_audit_pipeline(str(f))
                results.append({
                    "file": f.name,
                    "skipped": state.get("skipped", False),
                    "status": state.get("validation_status"),
                    "recommendation": state.get("recommendation"),
                    "invoice_id": state.get("invoice_id")
                })
            except Exception as e:
                logger.error(f"Error processing {f.name}: {e}")
                results.append({
                    "file": f.name,
                    "skipped": False,
                    "error": str(e)
                })

    return {"processed_count": len(results), "details": results}

@app.post("/rag/query")
def rag_query(req: RAGQueryRequest):
    """Answers a question through the five-agent RAG pipeline with Triad reflection."""
    logger.info(f"RAG query received: '{req.query}' (Invoice Filter: {req.invoice_id})")
    return query_rag_with_triad(req.query, invoice_id=req.invoice_id,
                                max_retries=req.max_retries, user=req.user or "auditor")

@app.post("/rag/index/{invoice_id}")
def rag_index_invoice(invoice_id: str):
    """Indexes one audited invoice into the vector store."""
    if not audit_db.get_invoice_details(invoice_id):
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")
    return index_invoice(invoice_id)

@app.post("/rag/rebuild")
def rag_rebuild(req: RebuildIndexRequest):
    """Rebuilds the whole vector index from PostgreSQL.

    This is the recovery path that makes Qdrant a derived store: after its volume
    is destroyed, this restores the RAG index without re-reading any source file.
    """
    return rebuild_index(req.review_statuses)

@app.get("/rag/stats")
def rag_stats():
    return {"vector_store": vector_store.stats(), "cache": response_cache.stats(),
            "config": (load_rules() or {}).get("rag", {})}

@app.get("/invoices")
def list_invoices():
    """Lists all audited invoices from the audit schema."""
    invoices = audit_db.list_invoices()
    return {"count": len(invoices), "invoices": invoices}

@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    """Returns detailed audit record, line items, discrepancies, and feedback."""
    details = audit_db.get_invoice_details(invoice_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")
    return details

@app.post("/invoices/{invoice_id}/feedback")
def submit_feedback(invoice_id: str, fb: FeedbackRequest):
    """Records human feedback/correction without overwriting original extraction."""
    fb_id = audit_db.insert_human_feedback(
        invoice_id=invoice_id,
        field_name=fb.field_name,
        original_value=fb.original_value,
        corrected_value=fb.corrected_value,
        corrected_by=fb.corrected_by or "Auditor"
    )
    return {"message": "Human feedback recorded successfully.", "feedback_id": fb_id}

# ------------------------------------------------------------------------------
# Human-in-the-Loop Review Gate Endpoints
# ------------------------------------------------------------------------------
_HEADER_FIELDS = {
    "invoice_number", "invoice_date", "vendor_id", "vendor_name", "po_number",
    "currency", "subtotal", "tax_amount", "total_amount"
}
_NUMERIC_FIELDS = {"subtotal", "tax_amount", "total_amount"}

def _jsonify(obj: Any) -> Any:
    """Recursively converts DB-native types (Decimal, date/datetime) into
    JSON-serializable values so downstream json.dumps calls don't fail."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    return obj

def _rebuild_state(invoice_id: str) -> Optional[Dict[str, Any]]:
    """Reconstructs an InvoiceState-shaped dict from the persisted audit record."""
    d = audit_db.get_invoice_details(invoice_id)
    if not d:
        return None
    raw = d.get("extracted_raw") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    line_items = _jsonify(d.get("line_items") or raw.get("line_items") or [])
    discrepancies = _jsonify(d.get("discrepancies") or [])
    return {
        "file_path": d.get("file_path") or f"invoice-{invoice_id}",
        "file_checksum": d.get("file_checksum") or "",
        "metadata": {},
        "skipped": False,
        "skip_reason": None,
        "extraction_method": d.get("extraction_method") or "",
        "raw_extracted_text": d.get("raw_extracted_text") or "",
        "source_language": d.get("source_language") or "en",
        "language_name": raw.get("language_name") or "English",
        "translated_text": d.get("translated_text") or "",
        "translation_confidence": float(d.get("translation_confidence") or 1.0),
        "invoice_number": d.get("invoice_number"),
        "invoice_date": str(d.get("invoice_date")) if d.get("invoice_date") else None,
        "vendor_id": d.get("vendor_id"),
        "vendor_name": d.get("vendor_name"),
        "po_number": d.get("po_number"),
        "currency": d.get("currency"),
        "subtotal": _jsonify(raw.get("subtotal")),
        "tax_amount": _jsonify(raw.get("tax_amount")),
        "total_amount": float(d["total_amount"]) if d.get("total_amount") is not None else None,
        "line_items": line_items,
        "extracted_raw": _jsonify(raw),
        "data_validation_passed": False,
        "data_validation_errors": [],
        "business_validation_passed": False,
        "discrepancies": discrepancies,
        "validation_status": d.get("validation_status") or "pending",
        "recommendation": d.get("recommendation") or "review",
        "risk_score": float(d.get("risk_score") or 0.0),
        "review_status": d.get("review_status") or "pending_review",
        "report_json_path": None,
        "report_html_path": None,
        "invoice_id": invoice_id,
        "thread_id": d.get("thread_id") or invoice_id,
        "rag_indexed": False,
        "error": None,
    }

@app.get("/review/queue")
def review_queue():
    """Lists invoices currently awaiting human approval (held from indexing)."""
    pending = [i for i in audit_db.list_invoices() if i.get("review_status") == "pending_review"]
    return {"count": len(pending), "invoices": pending}

@app.post("/invoices/{invoice_id}/revalidate")
def revalidate_invoice(invoice_id: str, req: RevalidateRequest):
    """Applies human edits, re-runs validation + reporting + risk scoring, and
    logs the corrections. The invoice stays in the review queue with an updated score."""
    state = _rebuild_state(invoice_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")

    applied: List[Dict[str, str]] = []

    for field, new_value in (req.corrections or {}).items():
        if field not in _HEADER_FIELDS:
            continue
        original = state.get(field)
        if str(original) == str(new_value):
            continue
        value: Any = new_value
        if field in _NUMERIC_FIELDS:
            try:
                value = float(new_value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Field '{field}' must be numeric.")
        state[field] = value
        state["extracted_raw"][field] = value
        applied.append({"field": field, "original": str(original), "corrected": str(value)})

    if req.line_items is not None:
        applied.append({"field": "line_items", "original": "(previous)", "corrected": "(edited)"})
        state["line_items"] = req.line_items
        state["extracted_raw"]["line_items"] = req.line_items

    # Re-run validation -> reporting (regenerates report + upserts DB) -> risk scoring.
    state = validator_node(state)
    state = reporter_node(state)
    rules = load_rules()
    score, _auto_status, reasons = compute_risk(state, rules)
    state["risk_score"] = score
    # After a human edit the invoice remains in the queue for an explicit decision.
    audit_db.update_review_status(invoice_id, "pending_review", risk_score=score)

    for a in applied:
        audit_db.record_correction(
            invoice_id=invoice_id, field_name=a["field"],
            original_value=a["original"], corrected_value=a["corrected"],
            corrected_by=req.reviewed_by or "Auditor", revalidated=True
        )

    return {
        "message": "Revalidation complete.",
        "invoice_id": invoice_id,
        "applied_corrections": applied,
        "validation_status": state.get("validation_status"),
        "recommendation": state.get("recommendation"),
        "risk_score": score,
        "review_status": "pending_review",
        "discrepancies": state.get("discrepancies", []),
        "data_validation_errors": state.get("data_validation_errors", []),
        "risk_reasons": reasons,
    }

@app.post("/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: str, req: DecisionRequest):
    """Approves an invoice: indexes it into the vector store and records the decision."""
    state = _rebuild_state(invoice_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")

    state = indexing_node(state)
    audit_db.update_review_status(
        invoice_id, "approved", reviewed_by=req.reviewed_by, review_notes=req.notes
    )
    audit_db.record_review_decision(invoice_id, "approved", reviewed_by=req.reviewed_by or "Auditor", notes=req.notes or "")
    return {
        "message": "Invoice approved and indexed into the vector store.",
        "invoice_id": invoice_id,
        "review_status": "approved",
        "rag_indexed": state.get("rag_indexed", False),
    }

@app.post("/invoices/{invoice_id}/reject")
def reject_invoice(invoice_id: str, req: DecisionRequest):
    """Rejects an invoice: records the decision and never indexes it."""
    if not audit_db.get_invoice_details(invoice_id):
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")
    audit_db.update_review_status(
        invoice_id, "rejected", reviewed_by=req.reviewed_by, review_notes=req.notes
    )
    audit_db.record_review_decision(invoice_id, "rejected", reviewed_by=req.reviewed_by or "Auditor", notes=req.notes or "")
    return {
        "message": "Invoice rejected. It will not be indexed into the vector store.",
        "invoice_id": invoice_id,
        "review_status": "rejected",
    }

# ------------------------------------------------------------------------------
# Watchdog Endpoints
# ------------------------------------------------------------------------------
@app.get("/watcher/status")
def get_watcher_status():
    """Returns real-time status, statistics, and recent events of the autonomous file watchdog."""
    watchdog = get_watchdog(incoming_dir=INCOMING_DIR)
    return watchdog.get_status()

@app.post("/watcher/toggle")
def toggle_watcher():
    """Toggles watchdog between paused and active states."""
    watchdog = get_watchdog(incoming_dir=INCOMING_DIR)
    status = watchdog.toggle()
    action = "resumed" if not status.get("is_paused") else "paused"
    return {"message": f"Watchdog successfully {action}.", "status": status}

@app.post("/watcher/scan")
def trigger_watcher_scan():
    """Forces an immediate on-demand scan cycle by the watchdog."""
    watchdog = get_watchdog(incoming_dir=INCOMING_DIR)
    results = watchdog.scan_cycle()
    return {
        "message": "Scan cycle executed successfully.",
        "results": results,
        "status": watchdog.get_status()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
