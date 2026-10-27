"""Explainable validation: Decimal arithmetic, configured tolerances, HTTP-only ERP."""
from decimal import Decimal
import httpx
from agent.models import Invoice, Finding
from agent.config import rules
D = Decimal

def completeness(invoice: Invoice, policy=None):
    policy = policy or rules()
    findings = []
    def add(field, actual, expected, message, line=None):
        findings.append(Finding(rule_id="completeness", field=field, actual=str(actual) if actual is not None else None,
            expected=str(expected), message=message, line_number=line))
    for field in policy["required_fields"]:
        if getattr(invoice, field, None) in (None, ""):
            add(field, None, "required", "Required invoice field is missing")
    if not invoice.line_items:
        add("line_items", None, "at least one", "Invoice has no line items")
    tolerance = D(policy["amount_tolerance"])
    for line in invoice.line_items:
        for field in policy["required_line_fields"]:
            if getattr(line, field) is None:
                add(field, None, "required", "Required line field is missing", line.line_number)
        if all(getattr(line, k) is not None for k in ("quantity", "unit_price", "line_total")):
            expected = line.quantity * line.unit_price
            if abs(expected - line.line_total) > tolerance:
                add("line_total", line.line_total, expected, "Quantity times price differs from line total", line.line_number)
    if invoice.line_items and all(x.line_total is not None for x in invoice.line_items):
        subtotal = sum((x.line_total for x in invoice.line_items), D(0))
        if invoice.subtotal is not None and abs(subtotal-invoice.subtotal)>tolerance:
            add("subtotal", invoice.subtotal, subtotal, "Line totals differ from subtotal")
        if invoice.tax_rate is not None and invoice.tax_amount is not None:
            expected_tax = (subtotal * invoice.tax_rate / 100).quantize(D("0.01"))
            if abs(expected_tax-invoice.tax_amount)>tolerance:
                add("tax_amount", invoice.tax_amount, expected_tax, "Tax calculation differs")
        if invoice.tax_rate is not None and invoice.tax_amount is None:
            add("tax_amount", None, "required with tax_rate", "Tax amount missing")
        expected_total = subtotal + (invoice.tax_amount or D(0)) + invoice.freight - invoice.discount
        if invoice.total_amount is not None and abs(invoice.total_amount-expected_total)>tolerance:
            add("total_amount", invoice.total_amount, expected_total, "Invoice total differs from lines plus tax/freight minus discount")
    return findings

def business(invoice: Invoice, erp_url: str, policy=None, transport=None):
    policy = policy or rules()
    findings = []
    def missing(field, message):
        findings.append(Finding(rule_id="erp_lookup", field=field, message=message))
    with httpx.Client(base_url=erp_url, timeout=15, transport=transport) as client:
        def get(kind, key):
            if not key:
                missing(kind, "Missing ERP lookup identifier")
                return None
            response = client.get(f"/{kind}/{key}")
            if response.status_code == 404:
                missing(kind, "ERP record not found")
                return None
            response.raise_for_status()
            return response.json()
        po = get("po", invoice.po_number)
        vendor = get("vendor", invoice.vendor_id)
        if not po:
            return findings
        def compare(field, actual, expected, tolerance="0", line=None):
            if actual is None or expected is None:
                missing(field, "Cannot compare missing value")
                return
            deviation = None
            if field in ("quantity", "unit_price"):
                a, e = D(str(actual)), D(str(expected))
                deviation = abs(a-e)/abs(e)*100 if e else (D(0) if a == e else None)
                mismatch = a != e if deviation is None else deviation > D(tolerance)
            else:
                mismatch = actual != expected
            if mismatch:
                findings.append(Finding(rule_id="erp_match", field=field, actual=str(actual), expected=str(expected),
                    deviation_percent=str(deviation) if deviation is not None else None,
                    message="Invoice differs from approved ERP record", line_number=line,
                    severity="reject" if deviation is not None and deviation >= D(policy.get("reject_deviation_percent","25")) else "review"))
        compare("currency", invoice.currency, po["currency"])
        compare("vendor_id", invoice.vendor_id, po["vendor_id"])
        if vendor:
            compare("vendor_name", invoice.vendor_name, vendor["name"])
        codes = [x.item_code for x in invoice.line_items]
        for line in invoice.line_items:
            get("sku", line.item_code)
            matches = [x for x in po["line_items"] if x["item_code"] == line.item_code]
            if len(matches)!=1 or codes.count(line.item_code)!=1:
                missing("item_code", "Missing or ambiguous item code; requires human review")
                continue
            ref = matches[0]
            compare("quantity", line.quantity, ref["quantity"], policy["quantity_tolerance_percent"], line.line_number)
            compare("unit_price", line.unit_price, ref["unit_price"], policy["price_tolerance_percent"], line.line_number)
        for line in po["line_items"]:
            if line["item_code"] not in codes:
                missing("item_code", "PO line absent from invoice: " + line["item_code"])
    return findings

def recommendation(findings, confidence):
    if any(f.severity == "reject" for f in findings): return "reject"
    return "review" if findings or confidence < rules()["translation_review_threshold"] else "approve"
