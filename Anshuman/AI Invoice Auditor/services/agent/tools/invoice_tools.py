"""
Invoice Processing Tools
========================
The six tools owned by the invoice-audit agent roles. Each one is a single,
testable capability with a declared schema; the agents hold no logic of their
own beyond deciding which tool to call and in what order.

  Invoice-Watcher Tool          -> Invoice-Monitor Agent
  Data Harvester Tool           -> Extractor Agent
  Lang-Bridge Tool              -> Translation Agent
  DataCompletenessChecker Tool  -> Invoice Data Validation Agent
  Business Validation Tool      -> Business Validation Agent
  Insight Reporter Tool         -> Reporting Agent
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .registry import registry
from ..config_loader import load_rules, load_prompts
from ..utils.cache import response_cache, make_key
from ..utils.db import audit_db
from ..utils.guardrails import guardrails
from ..utils.llm_client import llm_client

logger = logging.getLogger("tools.invoice")

MOCK_ERP_URL = os.getenv("MOCK_ERP_URL", "http://mock-erp:8000").rstrip("/")
INCOMING_DIR = Path(os.getenv("INCOMING_DIR", "/app/data/incoming"))
ERP_TIMEOUT = float(os.getenv("MOCK_ERP_TIMEOUT", "15"))


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _deviation_pct(invoice_value: float, erp_value: float) -> float:
    if erp_value in (0, None):
        return 100.0 if invoice_value else 0.0
    return round(abs(invoice_value - erp_value) / abs(erp_value) * 100.0, 2)


# ==============================================================================
# 1. Invoice-Watcher Tool
# ==============================================================================
@registry.tool(
    name="invoice_watcher",
    description=(
        "Monitors the designated mailbox drop directory for invoice attachments. Returns every "
        "detected file with its SHA-256 content checksum and whether that checksum has already "
        "been audited, so the same invoice is never audited twice under a different filename."
    ),
    agent="Invoice-Monitor Agent",
    input_schema={
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Directory to scan. Defaults to INCOMING_DIR."},
            "include_audited": {"type": "boolean", "default": False,
                                "description": "Include files whose checksum is already in the audit trail."},
        },
        "additionalProperties": False,
    },
)
def invoice_watcher(directory: Optional[str] = None, include_audited: bool = False) -> Dict[str, Any]:
    # Imported lazily: the watcher pulls in the workflow, which pulls in this tool layer.
    from ..watcher import SUPPORTED_EXTENSIONS, compute_checksum

    target = Path(directory) if directory else INCOMING_DIR
    if not target.exists():
        return {"directory": str(target), "exists": False, "detected": [], "new_files": 0}

    detected: List[Dict[str, Any]] = []
    for path in sorted(p for p in target.iterdir()
                       if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS):
        checksum = compute_checksum(str(path))
        already = bool(checksum) and audit_db.is_checksum_audited(checksum)
        if already and not include_audited:
            # Still reported, so "every detected file is recorded" holds.
            detected.append({"file_path": str(path), "file_name": path.name,
                             "checksum": checksum, "already_audited": True, "routed_to": "skip_duplicate"})
            continue
        detected.append({
            "file_path": str(path),
            "file_name": path.name,
            "size_bytes": path.stat().st_size,
            "checksum": checksum,
            "already_audited": already,
            "routed_to": _route_for(path.suffix.lower()),
        })
    return {
        "directory": str(target),
        "exists": True,
        "detected": detected,
        "new_files": sum(1 for d in detected if not d["already_audited"]),
    }


def _route_for(suffix: str) -> str:
    if suffix == ".pdf":
        return "pdf_text_then_ocr"
    if suffix in (".docx", ".doc"):
        return "docx_parser"
    return "ocr"


# ==============================================================================
# 2. Data Harvester Tool
# ==============================================================================
@registry.tool(
    name="data_harvester",
    description=(
        "Extracts raw text from a .pdf, .docx or image invoice. PDFs are read through their "
        "embedded text layer first and fall back to Tesseract OCR when no text layer exists. "
        "The complete raw text is returned so it can be persisted and the vector index rebuilt "
        "without ever re-reading the source document."
    ),
    agent="Extractor Agent",
    guardrails=["untrusted_document_fencing", "secret_stripping", "size_limit"],
    input_schema={
        "type": "object",
        "properties": {"file_path": {"type": "string", "description": "Absolute path of the invoice file."}},
        "required": ["file_path"],
        "additionalProperties": False,
    },
)
def data_harvester(file_path: str) -> Dict[str, Any]:
    from ..graph.nodes.extractor import extractor_node

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Invoice file not found: {file_path}")

    state: Dict[str, Any] = {"file_path": str(path), "file_checksum": "", "metadata": {},
                             "skipped": False, "skip_reason": None,
                             "extraction_method": "", "raw_extracted_text": ""}
    state = extractor_node(state)

    scan = guardrails.scan_document(state.get("raw_extracted_text", ""), source=path.name)
    return {
        "file_path": str(path),
        "file_checksum": state.get("file_checksum", ""),
        "extraction_method": state.get("extraction_method", ""),
        "raw_extracted_text": scan.text,
        "character_count": len(scan.text),
        "skipped": state.get("skipped", False),
        "skip_reason": state.get("skip_reason"),
        "guardrail_findings": scan.findings,
    }


# ==============================================================================
# 3. Lang-Bridge Tool
# ==============================================================================
@registry.tool(
    name="lang_bridge",
    description=(
        "Detects the source language of extracted invoice content and translates it into English, "
        "returning a translation confidence score. Results are cached by content hash in Redis so "
        "identical content is never translated twice."
    ),
    agent="Translation Agent",
    guardrails=["untrusted_document_fencing", "secret_stripping"],
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Raw extracted invoice text."},
            "use_cache": {"type": "boolean", "default": True},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
)
def lang_bridge(text: str, use_cache: bool = True) -> Dict[str, Any]:
    safe = guardrails.scan_document(text, source="translation_input")
    prompts = load_prompts().get("translation", {})
    system_prompt = prompts.get("system_prompt", "You are a multilingual invoice translator.")
    user_prompt = prompts.get("user_template", "{raw_text}").format(raw_text=safe.text)

    key = make_key("translation", llm_client.bedrock_model, safe.text)
    payload = response_cache.get(key) if use_cache else None
    cached = payload is not None

    if payload is None:
        raw = llm_client.completion(system_prompt, user_prompt, temperature=0.0)
        payload = _parse_translation(raw, fallback_text=safe.text)
        if use_cache:
            response_cache.set(key, payload)

    return {**payload, "cached": cached, "guardrail_findings": safe.findings}


def _parse_translation(raw: str, *, fallback_text: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if "```" in text:
        text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1]
    try:
        data = json.loads(text)
    except Exception:
        logger.warning("Translation response was not valid JSON. Passing source text through verbatim.")
        return {"source_language": "unknown", "language_name": "Unknown",
                "translated_text": fallback_text, "translation_confidence": 0.0}
    return {
        "source_language": data.get("source_language") or "unknown",
        "language_name": data.get("language_name") or "Unknown",
        "translated_text": data.get("translated_text") or fallback_text,
        "translation_confidence": float(data.get("translation_confidence") or 0.0),
    }


# ==============================================================================
# 4. DataCompletenessChecker Tool
# ==============================================================================
@registry.tool(
    name="data_completeness_checker",
    description=(
        "Validates a parsed invoice against the dynamic rules in config/rules.yaml: mandatory "
        "header and line-item fields, field data types, accepted currency, and internal arithmetic "
        "(line totals sum to the subtotal; subtotal + tax equals the invoice total)."
    ),
    agent="Invoice Data Validation Agent",
    input_schema={
        "type": "object",
        "properties": {
            "invoice": {"type": "object", "description": "Parsed invoice header fields."},
            "line_items": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["invoice"],
        "additionalProperties": False,
    },
)
def data_completeness_checker(invoice: Dict[str, Any],
                              line_items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    rules = load_rules() or {}
    required = rules.get("required_fields", {}) or {}
    tolerances = rules.get("tolerances", {}) or {}
    accepted = set(rules.get("accepted_currencies", []) or [])
    line_items = line_items if line_items is not None else (invoice.get("line_items") or [])

    errors: List[str] = []
    missing_fields: List[str] = []

    for field_name in required.get("header", []) or []:
        value = invoice.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing_fields.append(field_name)
            errors.append(f"Missing mandatory header field: {field_name}")

    for idx, item in enumerate(line_items, start=1):
        line_no = item.get("line_number", idx)
        for field_name in required.get("line_item", []) or []:
            value = item.get(field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing_fields.append(f"line_items[{line_no}].{field_name}")
                errors.append(f"Line {line_no}: missing mandatory field '{field_name}'")

    currency = invoice.get("currency")
    if currency and accepted and currency not in accepted:
        errors.append(f"Currency '{currency}' is not in the accepted list {sorted(accepted)}.")

    # -- arithmetic consistency ------------------------------------------------
    arithmetic: List[Dict[str, Any]] = []
    tol_pct = float(tolerances.get("tax_difference_percent", 5))

    for idx, item in enumerate(line_items, start=1):
        qty, price, total = _num(item.get("quantity")), _num(item.get("unit_price")), _num(item.get("line_total"))
        if qty is None or price is None or total is None:
            continue
        expected = round(qty * price, 2)
        if _deviation_pct(total, expected) > tol_pct:
            msg = (f"Line {item.get('line_number', idx)}: line_total {total} does not equal "
                   f"quantity x unit_price ({expected}).")
            errors.append(msg)
            arithmetic.append({"check": "line_total", "line_number": item.get("line_number", idx),
                               "stated": total, "expected": expected})

    line_sum = round(sum(_num(i.get("line_total")) or 0.0 for i in line_items), 2)
    subtotal = _num(invoice.get("subtotal"))
    tax = _num(invoice.get("tax_amount")) or 0.0
    total_amount = _num(invoice.get("total_amount"))

    if subtotal is not None and line_items and _deviation_pct(subtotal, line_sum) > tol_pct:
        errors.append(f"Subtotal {subtotal} does not match the sum of line totals ({line_sum}).")
        arithmetic.append({"check": "subtotal", "stated": subtotal, "expected": line_sum})

    if total_amount is not None:
        expected_total = round((subtotal if subtotal is not None else line_sum) + tax, 2)
        if _deviation_pct(total_amount, expected_total) > tol_pct:
            errors.append(f"Total {total_amount} does not equal subtotal + tax ({expected_total}).")
            arithmetic.append({"check": "total_amount", "stated": total_amount, "expected": expected_total})

    return {
        "passed": not errors,
        "errors": errors,
        "missing_fields": missing_fields,
        "arithmetic_checks": arithmetic,
        "rules_version": rules.get("version", "rules.yaml"),
    }


# ==============================================================================
# 5. Business Validation Tool
# ==============================================================================
@registry.tool(
    name="business_validation",
    description=(
        "Cross-verifies a parsed invoice against the enterprise system through the mock-erp HTTP "
        "service (never by querying the ERP database directly). Compares vendor, currency, "
        "quantity and unit price against the matching purchase order and emits one discrepancy "
        "row per mismatched field with both values and the deviation percentage."
    ),
    agent="Business Validation Agent",
    input_schema={
        "type": "object",
        "properties": {
            "invoice": {"type": "object"},
            "line_items": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["invoice"],
        "additionalProperties": False,
    },
)
def business_validation(invoice: Dict[str, Any],
                        line_items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    rules = load_rules() or {}
    tolerances = rules.get("tolerances", {}) or {}
    price_tol = float(tolerances.get("price_difference_percent", 5))
    qty_tol = float(tolerances.get("quantity_difference_percent", 0))
    line_items = line_items if line_items is not None else (invoice.get("line_items") or [])

    discrepancies: List[Dict[str, Any]] = []
    po_number = invoice.get("po_number")

    if not po_number:
        return {
            "passed": False,
            "erp_reachable": True,
            "po_number": None,
            "discrepancies": [{
                "field_name": "po_number", "invoice_value": None, "erp_value": None,
                "deviation_pct": 100.0, "severity": "CRITICAL",
                "message": "No purchase order number on the invoice; it cannot be matched to the ERP.",
            }],
        }

    po = _erp_get(f"/po/{po_number}")
    if po is None:
        return {
            "passed": False, "erp_reachable": True, "po_number": po_number,
            "discrepancies": [{
                "field_name": "po_number", "invoice_value": po_number, "erp_value": None,
                "deviation_pct": 100.0, "severity": "CRITICAL",
                "message": f"Purchase order '{po_number}' does not exist in the ERP.",
            }],
        }

    # -- vendor ---------------------------------------------------------------
    erp_vendor_id = po.get("vendor_id")
    vendor = _erp_get(f"/vendor/{erp_vendor_id}") if erp_vendor_id else None
    invoice_vendor_id = invoice.get("vendor_id")
    if invoice_vendor_id and erp_vendor_id and invoice_vendor_id != erp_vendor_id:
        discrepancies.append({
            "field_name": "vendor_id", "invoice_value": invoice_vendor_id, "erp_value": erp_vendor_id,
            "deviation_pct": 100.0, "severity": "CRITICAL",
            "message": f"Invoice vendor '{invoice_vendor_id}' does not own purchase order {po_number}.",
        })

    erp_currency = (vendor or {}).get("currency")
    invoice_currency = invoice.get("currency")
    if erp_currency and invoice_currency and erp_currency != invoice_currency:
        discrepancies.append({
            "field_name": "currency", "invoice_value": invoice_currency, "erp_value": erp_currency,
            "deviation_pct": 100.0, "severity": "ERROR",
            "message": f"Invoice billed in {invoice_currency} but the vendor master is {erp_currency}.",
        })

    # -- line items -----------------------------------------------------------
    erp_lines = {str(l.get("item_code")): l for l in (po.get("line_items") or [])}
    for idx, item in enumerate(line_items, start=1):
        line_no = item.get("line_number", idx)
        code = str(item.get("item_code") or "")
        erp_line = erp_lines.get(code)
        if erp_line is None:
            discrepancies.append({
                "field_name": f"line_items[{line_no}].item_code", "invoice_value": code,
                "erp_value": None, "deviation_pct": 100.0, "severity": "CRITICAL",
                "message": f"Item '{code}' is billed but is not on purchase order {po_number}.",
            })
            continue

        for field_name, erp_key, tol, severity in (
            ("quantity", "qty", qty_tol, "ERROR"),
            ("unit_price", "unit_price", price_tol, "ERROR"),
        ):
            inv_val, erp_val = _num(item.get(field_name)), _num(erp_line.get(erp_key))
            if inv_val is None or erp_val is None:
                continue
            deviation = _deviation_pct(inv_val, erp_val)
            if deviation > tol:
                discrepancies.append({
                    "field_name": f"line_items[{line_no}].{field_name}",
                    "invoice_value": inv_val, "erp_value": erp_val,
                    "deviation_pct": deviation,
                    "severity": "CRITICAL" if deviation > tol * 4 else severity,
                    "message": (f"Line {line_no} {field_name}: invoiced {inv_val} vs ERP {erp_val} "
                                f"({deviation}% deviation, tolerance {tol}%)."),
                })

        erp_line_currency = erp_line.get("currency")
        if erp_line_currency and invoice_currency and erp_line_currency != invoice_currency:
            discrepancies.append({
                "field_name": f"line_items[{line_no}].currency",
                "invoice_value": invoice_currency, "erp_value": erp_line_currency,
                "deviation_pct": 100.0, "severity": "ERROR",
                "message": f"Line {line_no} currency mismatch against purchase order {po_number}.",
            })

    # Items ordered but not billed are informational, not failures.
    billed = {str(i.get("item_code") or "") for i in line_items}
    for code in sorted(set(erp_lines) - billed):
        discrepancies.append({
            "field_name": "po_line_coverage", "invoice_value": None, "erp_value": code,
            "deviation_pct": 0.0, "severity": "INFO",
            "message": f"Purchase order item '{code}' is not billed on this invoice.",
        })

    return {
        "passed": not any(d["severity"] in ("CRITICAL", "ERROR") for d in discrepancies),
        "erp_reachable": True,
        "po_number": po_number,
        "erp_vendor": vendor,
        "erp_po": po,
        "discrepancies": discrepancies,
    }


def _erp_get(path: str) -> Optional[Dict[str, Any]]:
    """Reads ERP data strictly over the mock-erp HTTP API by service name."""
    url = f"{MOCK_ERP_URL}{path}"
    try:
        resp = httpx.get(url, timeout=ERP_TIMEOUT)
    except httpx.HTTPError as e:
        raise RuntimeError(f"mock-erp service is unreachable at {url}: {e}") from e
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


@registry.tool(
    name="erp_lookup",
    description=("Direct read-through to a single mock-erp endpoint (purchase order, vendor or SKU "
                 "master record). Used by the dashboard and for discrepancy drill-down."),
    agent="Business Validation Agent",
    input_schema={
        "type": "object",
        "properties": {
            "resource": {"type": "string", "enum": ["po", "vendor", "sku"]},
            "identifier": {"type": "string"},
        },
        "required": ["resource", "identifier"],
        "additionalProperties": False,
    },
)
def erp_lookup(resource: str, identifier: str) -> Dict[str, Any]:
    record = _erp_get(f"/{resource}/{identifier}")
    return {"resource": resource, "identifier": identifier, "found": record is not None, "record": record}


# ==============================================================================
# 6. Insight Reporter Tool
# ==============================================================================
@registry.tool(
    name="insight_reporter",
    description=(
        "Produces the auditor-facing outcome for an invoice: a JSON report for machines and an "
        "HTML report for humans, covering the discrepancy summary, missing field list, translation "
        "confidence and the approve / manual-review / reject recommendation. The outcome is written "
        "to PostgreSQL, which is the system of record; the files are a convenience copy."
    ),
    agent="Reporting Agent",
    read_only=False,
    guardrails=["pii_redaction"],
    input_schema={
        "type": "object",
        "properties": {"state": {"type": "object", "description": "Full InvoiceState for the audited invoice."}},
        "required": ["state"],
        "additionalProperties": False,
    },
)
def insight_reporter(state: Dict[str, Any]) -> Dict[str, Any]:
    from ..graph.nodes.reporter import reporter_node

    result = reporter_node(guardrails.scan_report(dict(state)))
    return {
        "invoice_id": result.get("invoice_id"),
        "report_json_path": result.get("report_json_path"),
        "report_html_path": result.get("report_html_path"),
        "validation_status": result.get("validation_status"),
        "recommendation": result.get("recommendation"),
        "translation_confidence": result.get("translation_confidence"),
        "discrepancy_count": len(result.get("discrepancies") or []),
        "missing_field_count": len(result.get("data_validation_errors") or []),
    }
