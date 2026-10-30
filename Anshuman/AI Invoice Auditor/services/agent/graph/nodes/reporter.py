"""
Reporting Node
Generates JSON and HTML audit reports and persists the invoice, line items,
and discrepancies into the PostgreSQL audit schema.
Addresses requirement 3.5.
"""

import os
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime
from ..state import InvoiceState
from ...config_loader import load_rules
from ...utils.db import audit_db

logger = logging.getLogger("reporter_node")

BASE_DIR = Path(__file__).resolve().parents[4]
OUTPUTS_DIR = BASE_DIR / "outputs" / "reports"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

def generate_html_report(state: InvoiceState, report_data: dict) -> str:
    status_color = "#10b981" if state["validation_status"] == "passed" else ("#f59e0b" if state["validation_status"] == "partial" else "#ef4444")
    
    rows_lines = ""
    for idx, item in enumerate(state.get("line_items", [])):
        rows_lines += f"""
        <tr>
            <td>{idx + 1}</td>
            <td><code>{item.get('item_code', 'N/A')}</code></td>
            <td>{item.get('description', '')}</td>
            <td>{item.get('quantity', item.get('qty', 0))}</td>
            <td>{item.get('unit_price', 0):.2f}</td>
            <td><strong>{item.get('line_total', 0):.2f}</strong></td>
        </tr>
        """

    rows_discrepancies = ""
    discrepancies = state.get("discrepancies", [])
    if discrepancies:
        for d in discrepancies:
            sev_badge = f'<span style="background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:4px;font-weight:bold;">{d.get("severity")}</span>'
            rows_discrepancies += f"""
            <tr>
                <td><strong>{d.get('field_name')}</strong></td>
                <td>{d.get('invoice_value')}</td>
                <td>{d.get('erp_value')}</td>
                <td>{d.get('deviation_pct', 0):.1f}%</td>
                <td>{sev_badge}</td>
            </tr>
            """
    else:
        rows_discrepancies = "<tr><td colspan='5' style='text-align:center;color:#10b981;'>No discrepancies detected. ERP validation passed!</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Audit Report – {state.get('invoice_number', 'Unknown')}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 30px; background: #f8fafc; color: #1e293b; }}
        .card {{ background: white; padding: 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px; }}
        h1, h2, h3 {{ color: #0f172a; margin-top: 0; }}
        .header-meta {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #e2e8f0; padding-bottom: 16px; margin-bottom: 16px; }}
        .badge {{ padding: 6px 14px; border-radius: 9999px; font-weight: 700; color: white; display: inline-block; text-transform: uppercase; font-size: 13px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        th, td {{ border: 1px solid #e2e8f0; padding: 10px 12px; text-align: left; font-size: 14px; }}
        th {{ background: #f1f5f9; color: #475569; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 16px; }}
        .meta-item {{ background: #f8fafc; padding: 12px; border-radius: 6px; border: 1px solid #e2e8f0; }}
        .meta-item span {{ display: block; font-size: 12px; color: #64748b; font-weight: 600; text-transform: uppercase; }}
        .meta-item strong {{ font-size: 16px; color: #0f172a; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header-meta">
            <div>
                <h1>Audit Report: {state.get('invoice_number') or 'Invoice (Incomplete)'}</h1>
                <p style="color:#64748b; margin: 4px 0 0 0;">Processed: {report_data.get('timestamp')}</p>
            </div>
            <div>
                <span class="badge" style="background:{status_color}">{state['validation_status']}</span>
                <span class="badge" style="background:#3b82f6; margin-left:8px;">Recommendation: {state['recommendation']}</span>
            </div>
        </div>

        <div class="grid">
            <div class="meta-item"><span>Vendor Name</span><strong>{state.get('vendor_name') or 'N/A'}</strong></div>
            <div class="meta-item"><span>Vendor ID</span><strong>{state.get('vendor_id') or 'N/A'}</strong></div>
            <div class="meta-item"><span>Purchase Order</span><strong>{state.get('po_number') or 'N/A'}</strong></div>
            <div class="meta-item"><span>Invoice Date</span><strong>{state.get('invoice_date') or 'N/A'}</strong></div>
            <div class="meta-item"><span>Currency</span><strong>{state.get('currency') or 'N/A'}</strong></div>
            <div class="meta-item"><span>Total Amount</span><strong>{state.get('total_amount') or 0.0:.2f}</strong></div>
            <div class="meta-item"><span>Language</span><strong>{state.get('language_name')} ({state.get('source_language')})</strong></div>
            <div class="meta-item"><span>Translation Conf.</span><strong>{state.get('translation_confidence', 1.0):.2f}</strong></div>
        </div>
    </div>

    <div class="card">
        <h2>Discrepancies & Business Validation</h2>
        <table>
            <thead>
                <tr>
                    <th>Field / Rule</th>
                    <th>Invoice Value</th>
                    <th>ERP Value</th>
                    <th>Deviation</th>
                    <th>Severity</th>
                </tr>
            </thead>
            <tbody>
                {rows_discrepancies}
            </tbody>
        </table>
    </div>

    <div class="card">
        <h2>Extracted Line Items</h2>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>SKU Code</th>
                    <th>Description</th>
                    <th>Quantity</th>
                    <th>Unit Price</th>
                    <th>Line Total</th>
                </tr>
            </thead>
            <tbody>
                {rows_lines}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    return html

def reporter_node(state: InvoiceState) -> InvoiceState:
    if state.get("skipped"):
        return state

    rules = load_rules()
    policies = rules.get("validation_policies", {})
    auto_thresh = policies.get("auto_approve_confidence_threshold", 0.95)

    discrepancies = state.get("discrepancies", [])
    data_errors = state.get("data_validation_errors", [])
    has_critical = any(d.get("severity") in ["CRITICAL", "ERROR"] for d in discrepancies) or len(data_errors) > 0

    # Determine status
    if len(discrepancies) == 0 and len(data_errors) == 0:
        val_status = "passed"
    elif not has_critical:
        val_status = "partial"
    else:
        val_status = "failed"

    # Determine recommendation
    if val_status == "passed" and state.get("translation_confidence", 1.0) >= auto_thresh:
        recommendation = "approve"
    elif val_status == "failed" and any(d.get("field_name") == "currency" for d in discrepancies):
        recommendation = "reject"
    elif val_status == "failed" and any("Missing mandatory header" in e for e in data_errors):
        recommendation = "reject"
    else:
        recommendation = "manual_review"

    state["validation_status"] = val_status
    state["recommendation"] = recommendation

    # Generate Report Data
    invoice_id = state.get("invoice_id") or str(uuid.uuid4())
    state["invoice_id"] = invoice_id

    report_data = {
        "invoice_id": invoice_id,
        "invoice_number": state.get("invoice_number"),
        "vendor_id": state.get("vendor_id"),
        "vendor_name": state.get("vendor_name"),
        "po_number": state.get("po_number"),
        "currency": state.get("currency"),
        "total_amount": state.get("total_amount"),
        "source_language": state.get("source_language"),
        "translation_confidence": state.get("translation_confidence"),
        "validation_status": val_status,
        "recommendation": recommendation,
        "data_validation_errors": data_errors,
        "discrepancies": discrepancies,
        "line_items": state.get("line_items", []),
        "timestamp": datetime.utcnow().isoformat()
    }

    # Write JSON and HTML reports
    file_stem = Path(state["file_path"]).stem
    json_path = OUTPUTS_DIR / f"{file_stem}_report.json"
    html_path = OUTPUTS_DIR / f"{file_stem}_report.html"

    # Report files are secondary; the database is the system of record. A failure
    # to write them (e.g. read-only mount) must not abort audit persistence.
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        html_content = generate_html_report(state, report_data)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        state["report_json_path"] = str(json_path)
        state["report_html_path"] = str(html_path)
    except OSError as e:
        logger.warning(f"Could not write report files for {invoice_id} ({e}). Persisting to DB only.")
        state["report_json_path"] = None
        state["report_html_path"] = None

    # Persist in PostgreSQL Audit schema
    audit_data = {
        "invoice_id": invoice_id,
        "file_path": state["file_path"],
        "file_checksum": state["file_checksum"],
        "extraction_method": state.get("extraction_method"),
        "raw_extracted_text": state.get("raw_extracted_text"),
        "translated_text": state.get("translated_text"),
        "source_language": state.get("source_language"),
        "translation_confidence": state.get("translation_confidence"),
        "invoice_number": state.get("invoice_number"),
        "vendor_name": state.get("vendor_name"),
        "vendor_id": state.get("vendor_id"),
        "po_number": state.get("po_number"),
        "invoice_date": state.get("invoice_date"),
        "currency": state.get("currency"),
        "total_amount": state.get("total_amount"),
        "validation_status": val_status,
        "recommendation": recommendation,
        "extracted_raw": state.get("extracted_raw", {}),
        "thread_id": state.get("thread_id") or state.get("invoice_id")
    }

    audit_db.insert_invoice_audit(audit_data)
    audit_db.insert_line_items(invoice_id, state.get("line_items", []))
    audit_db.insert_discrepancies(invoice_id, discrepancies)

    logger.info(f"Persisted invoice {invoice_id} to audit database. Status: {val_status}, Rec: {recommendation}")
    return state
