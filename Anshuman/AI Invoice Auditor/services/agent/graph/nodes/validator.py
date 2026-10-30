"""
Validation Node
Executes two distinct validation stages:
  1. Data Validation Agent: Checks field completeness, data types, and internal arithmetic against config/rules.yaml.
  2. Business Validation Agent: Queries the mock-erp HTTP service to validate PO, Vendor, and SKU line items within configured tolerances.
"""

import os
import logging
import json
from typing import Dict, Any, List, Optional
import httpx
from ..state import InvoiceState, Discrepancy
from ...config_loader import load_rules

logger = logging.getLogger("validator_node")

MOCK_ERP_URL = os.getenv("MOCK_ERP_URL", "http://localhost:8000")

def _resolve_vendor_id(state: InvoiceState) -> Optional[str]:
    """Resolves vendor_id from vendor_name using vendors.json if missing."""
    if state.get("vendor_id"):
        return state["vendor_id"]

    vendor_name = (state.get("vendor_name") or "").strip().lower()
    if not vendor_name:
        return None

    paths = [
        "/app/data/vendors.json",
        os.path.join(os.getcwd(), "data", "vendors.json"),
        "vendors.json"
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for v in json.load(f):
                        if v.get("vendor_name", "").lower() in vendor_name or vendor_name in v.get("vendor_name", "").lower():
                            state["vendor_id"] = v.get("vendor_id")
                            return state["vendor_id"]
            except Exception:
                pass
    return None

def run_data_validation(state: InvoiceState, rules: Dict[str, Any]) -> List[str]:
    """Checks header completeness, line item completeness, currency validity, and arithmetic."""
    errors = []
    req_header = rules.get("required_fields", {}).get("header", [])
    accepted_currencies = rules.get("accepted_currencies", ["USD", "EUR", "INR", "GBP"])
    currency_map = rules.get("currency_symbol_map", {})

    # Auto-resolve vendor code from name
    _resolve_vendor_id(state)

    # Check required header fields with alias fallback
    header_mapping = {
        "invoice_no": state.get("invoice_number") or state.get("invoice_no"),
        "invoice_date": state.get("invoice_date"),
        "vendor_id": state.get("vendor_id") or state.get("vendor_name"),
        "currency": state.get("currency"),
        "total_amount": state.get("total_amount")
    }

    for f in req_header:
        val = header_mapping.get(f, state.get(f))
        if val is None or str(val).strip() in ("", "None", "null"):
            errors.append(f"Missing mandatory header field: '{f}'")

    # Validate Currency
    curr = state.get("currency")
    if curr:
        normalized_curr = currency_map.get(curr, curr.upper())
        state["currency"] = normalized_curr
        if normalized_curr not in accepted_currencies:
            errors.append(f"Currency '{curr}' is not in accepted list: {accepted_currencies}")

    # Check Line Items
    line_items = state.get("line_items", [])
    if not line_items:
        errors.append("No line items found in invoice.")
    else:
        req_line = rules.get("required_fields", {}).get("line_item", [])
        calculated_subtotal = 0.0
        for idx, item in enumerate(line_items):
            for lf in req_line:
                # normalize field name check
                item_val = item.get(lf, item.get(lf.replace("qty", "quantity").replace("total", "line_total")))
                if item_val is None:
                    errors.append(f"Line {idx + 1}: Missing mandatory field '{lf}'")

            q = float(item.get("quantity", item.get("qty", 0.0)))
            p = float(item.get("unit_price", 0.0))
            calculated_subtotal += (q * p)

        # Check total arithmetic (including parsed tax)
        inv_total = state.get("total_amount")
        tax_amount = float(state.get("tax_amount") or 0.0)
        expected_total = calculated_subtotal + tax_amount

        if inv_total is not None and calculated_subtotal > 0:
            deviation = abs(inv_total - expected_total)
            dev_pct = (deviation / expected_total) * 100.0 if expected_total > 0 else 0.0
            if dev_pct > 5.0 and deviation > 1.0:
                errors.append(
                    f"Arithmetic discrepancy: Expected total ({expected_total:.2f}) "
                    f"differs from Total Amount ({inv_total:.2f}) by {dev_pct:.1f}%"
                )

    return errors

def run_business_validation(state: InvoiceState, rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Validates invoice fields and line items against the mock ERP service over HTTP."""
    discrepancies = []
    po_number = state.get("po_number")
    if not po_number:
        discrepancies.append({
            "field_name": "po_number",
            "invoice_value": "None",
            "erp_value": "Required",
            "deviation_pct": 100.0,
            "severity": "CRITICAL"
        })
        return discrepancies

    tolerances = rules.get("tolerances", {})
    price_tol_pct = float(tolerances.get("price_difference_percent", 5))
    qty_tol_pct = float(tolerances.get("quantity_difference_percent", 0))

    try:
        with httpx.Client(base_url=MOCK_ERP_URL, timeout=5.0) as client:
            # 1. Look up PO
            po_resp = client.get(f"/po/{po_number}")
            if po_resp.status_code != 200:
                discrepancies.append({
                    "field_name": "po_number",
                    "invoice_value": po_number,
                    "erp_value": "NOT FOUND",
                    "deviation_pct": 100.0,
                    "severity": "CRITICAL"
                })
                return discrepancies

            po_data = po_resp.json()
            erp_vendor_id = po_data.get("vendor_id")
            erp_line_items = {item["item_code"]: item for item in po_data.get("line_items", [])}

            # 2. Check Vendor Match
            inv_vendor_id = state.get("vendor_id")
            if inv_vendor_id and inv_vendor_id != erp_vendor_id:
                discrepancies.append({
                    "field_name": "vendor_id",
                    "invoice_value": inv_vendor_id,
                    "erp_value": erp_vendor_id,
                    "deviation_pct": 100.0,
                    "severity": "ERROR"
                })

            # Look up Vendor Details
            if erp_vendor_id:
                v_resp = client.get(f"/vendor/{erp_vendor_id}")
                if v_resp.status_code == 200:
                    v_data = v_resp.json()
                    expected_curr = v_data.get("currency")
                    if state.get("currency") and state.get("currency") != expected_curr:
                        discrepancies.append({
                            "field_name": "currency",
                            "invoice_value": state.get("currency"),
                            "erp_value": expected_curr,
                            "deviation_pct": 100.0,
                            "severity": "ERROR"
                        })

            # 3. Check Line Items against PO
            inv_lines = state.get("line_items", [])
            for item in inv_lines:
                sku = item.get("item_code")
                if not sku:
                    continue

                # Verify SKU existence in ERP SKU Master
                sku_resp = client.get(f"/sku/{sku}")
                if sku_resp.status_code != 200:
                    discrepancies.append({
                        "field_name": f"sku_master_{sku}",
                        "invoice_value": sku,
                        "erp_value": "NOT IN MASTER",
                        "deviation_pct": 100.0,
                        "severity": "WARNING"
                    })

                # Check if item exists in PO
                if sku not in erp_line_items:
                    discrepancies.append({
                        "field_name": f"item_code_{sku}",
                        "invoice_value": f"Present ({sku})",
                        "erp_value": f"Not in {po_number}",
                        "deviation_pct": 100.0,
                        "severity": "ERROR"
                    })
                    continue

                po_item = erp_line_items[sku]
                inv_qty = float(item.get("quantity", item.get("qty", 0.0)))
                erp_qty = float(po_item.get("qty", 0.0))
                inv_price = float(item.get("unit_price", 0.0))
                erp_price = float(po_item.get("unit_price", 0.0))

                # Quantity Check (tolerance: 0%)
                if erp_qty > 0:
                    qty_diff_pct = abs(inv_qty - erp_qty) / erp_qty * 100.0
                    if qty_diff_pct > qty_tol_pct:
                        discrepancies.append({
                            "field_name": f"qty_{sku}",
                            "invoice_value": str(inv_qty),
                            "erp_value": str(erp_qty),
                            "deviation_pct": round(qty_diff_pct, 2),
                            "severity": "ERROR"
                        })

                # Unit Price Check (tolerance: ±5%)
                if erp_price > 0:
                    price_diff_pct = abs(inv_price - erp_price) / erp_price * 100.0
                    if price_diff_pct > price_tol_pct:
                        discrepancies.append({
                            "field_name": f"unit_price_{sku}",
                            "invoice_value": f"{inv_price:.2f}",
                            "erp_value": f"{erp_price:.2f}",
                            "deviation_pct": round(price_diff_pct, 2),
                            "severity": "WARNING" if price_diff_pct <= 10 else "ERROR"
                        })

    except Exception as e:
        logger.warning(f"HTTP call to {MOCK_ERP_URL} failed ({e}). Utilizing ERP database fallback for local execution.")
        try:
            from services.mock_erp.db import erp_db
            po_data = erp_db.get_po(po_number)
            if not po_data:
                discrepancies.append({
                    "field_name": "po_number",
                    "invoice_value": po_number,
                    "erp_value": "NOT FOUND",
                    "deviation_pct": 100.0,
                    "severity": "CRITICAL"
                })
                return discrepancies

            erp_vendor_id = po_data.get("vendor_id")
            erp_line_items = {item["item_code"]: item for item in po_data.get("line_items", [])}

            inv_vendor_id = state.get("vendor_id")
            if inv_vendor_id and inv_vendor_id != erp_vendor_id:
                discrepancies.append({
                    "field_name": "vendor_id",
                    "invoice_value": inv_vendor_id,
                    "erp_value": erp_vendor_id,
                    "deviation_pct": 100.0,
                    "severity": "ERROR"
                })

            if erp_vendor_id:
                v_data = erp_db.get_vendor(erp_vendor_id)
                if v_data:
                    expected_curr = v_data.get("currency")
                    if state.get("currency") and state.get("currency") != expected_curr:
                        discrepancies.append({
                            "field_name": "currency",
                            "invoice_value": state.get("currency"),
                            "erp_value": expected_curr,
                            "deviation_pct": 100.0,
                            "severity": "ERROR"
                        })

            inv_lines = state.get("line_items", [])
            for item in inv_lines:
                sku = item.get("item_code")
                if not sku:
                    continue

                sku_data = erp_db.get_sku(sku)
                if not sku_data:
                    discrepancies.append({
                        "field_name": f"sku_master_{sku}",
                        "invoice_value": sku,
                        "erp_value": "NOT IN MASTER",
                        "deviation_pct": 100.0,
                        "severity": "WARNING"
                    })

                if sku not in erp_line_items:
                    discrepancies.append({
                        "field_name": f"item_code_{sku}",
                        "invoice_value": f"Present ({sku})",
                        "erp_value": f"Not in {po_number}",
                        "deviation_pct": 100.0,
                        "severity": "ERROR"
                    })
                    continue

                po_item = erp_line_items[sku]
                inv_qty = float(item.get("quantity", item.get("qty", 0.0)))
                erp_qty = float(po_item.get("qty", 0.0))
                inv_price = float(item.get("unit_price", 0.0))
                erp_price = float(po_item.get("unit_price", 0.0))

                if erp_qty > 0:
                    qty_diff_pct = abs(inv_qty - erp_qty) / erp_qty * 100.0
                    if qty_diff_pct > qty_tol_pct:
                        discrepancies.append({
                            "field_name": f"qty_{sku}",
                            "invoice_value": str(inv_qty),
                            "erp_value": str(erp_qty),
                            "deviation_pct": round(qty_diff_pct, 2),
                            "severity": "ERROR"
                        })

                if erp_price > 0:
                    price_diff_pct = abs(inv_price - erp_price) / erp_price * 100.0
                    if price_diff_pct > price_tol_pct:
                        discrepancies.append({
                            "field_name": f"unit_price_{sku}",
                            "invoice_value": f"{inv_price:.2f}",
                            "erp_value": f"{erp_price:.2f}",
                            "deviation_pct": round(price_diff_pct, 2),
                            "severity": "WARNING" if price_diff_pct <= 10 else "ERROR"
                        })
        except Exception as fallback_err:
            logger.error(f"ERP fallback error: {fallback_err}")
            discrepancies.append({
                "field_name": "erp_service_call",
                "invoice_value": "N/A",
                "erp_value": f"HTTP Error: {e}",
                "deviation_pct": 100.0,
                "severity": "CRITICAL"
            })

    return discrepancies

def validator_node(state: InvoiceState) -> InvoiceState:
    if state.get("skipped"):
        return state

    rules = load_rules()

    # 1. Invoice Data Validation
    data_errors = run_data_validation(state, rules)
    state["data_validation_errors"] = data_errors
    state["data_validation_passed"] = len(data_errors) == 0

    # 2. Business Validation (Mock ERP HTTP)
    discrepancies = run_business_validation(state, rules)
    # Add data errors as discrepancies if any
    for err in data_errors:
        discrepancies.append({
            "field_name": "data_validation",
            "invoice_value": "Invalid/Missing",
            "erp_value": err,
            "deviation_pct": 100.0,
            "severity": "ERROR"
        })

    state["discrepancies"] = discrepancies
    state["business_validation_passed"] = len(discrepancies) == 0

    logger.info(
        f"Validation complete: Data errors={len(data_errors)}, "
        f"Discrepancies={len(discrepancies)}"
    )
    return state
