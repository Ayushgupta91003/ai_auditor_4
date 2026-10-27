"""Escaped, printable audit exports. Backward-compatible with earlier stored reports."""
from html import escape

def display(value):return escape("—" if value is None else str(value))
def table(headers,rows):
    cells="".join("<tr>"+"".join("<td>"+display(value)+"</td>" for value in row)+"</tr>" for row in rows)
    if not cells:cells='<tr><td colspan="'+str(len(headers))+'">No discrepancies found.</td></tr>'
    return '<table><thead><tr>'+"".join("<th>"+display(h)+"</th>" for h in headers)+"</tr></thead><tbody>"+cells+"</tbody></table>"
def render_html(report):
    invoice=report.get("invoice") or {}
    title=invoice.get("invoice_number") or "Invoice audit"
    header="".join("<div><dt>"+display(label)+"</dt><dd>"+display(value)+"</dd></div>" for label,value in [
        ("Invoice number",invoice.get("invoice_number")),("Date",invoice.get("invoice_date")),
        ("Vendor",invoice.get("vendor_name")),("Purchase order",invoice.get("po_number")),
        ("Invoice total",str(invoice.get("total_amount") or "—")+" "+str(invoice.get("currency") or "")),
        ("Report version",report.get("version"))])
    findings=table(["Line","Field","Invoice","Expected","Deviation %","Explanation"],[[f.get(k) for k in ("line_number","field","actual","expected","deviation_percent","message")] for f in report["findings"]])
    lines=table(["#","Item code","Description","Quantity","Unit price","Line total"],[[line.get(k) for k in ("line_number","item_code","description","quantity","unit_price","line_total")] for line in invoice.get("line_items",[])]) if invoice.get("line_items") else ""
    missing=", ".join(report.get("missing_fields",[])) or "None"
    style="body{font:15px Arial;color:#172b43;max-width:1100px;margin:35px auto;padding:25px;line-height:1.55}h1{margin-bottom:6px}h2{font-size:19px;margin-top:30px}dl{display:flex;flex-wrap:wrap;gap:22px;background:#f1f5fa;padding:18px}dt{font-size:12px;color:#607086}dd{margin:3px 0 0;font-weight:600}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:10px;text-align:left;border-bottom:1px solid #d7dfeb}th{background:#edf2f8}.outcome{font-size:20px;font-weight:bold}.note{font-size:12px;color:#607086}@media print{body{margin:0;padding:10px}tr{break-inside:avoid}}"
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Invoice audit - '+display(title)+'</title><style>'+style+'</style></head><body><h1>Invoice audit</h1><h2>'+display(title)+'</h2><dl>'+header+'</dl><p class="outcome">Recommendation: '+display(report["recommendation"].upper())+'</p><p>'+display(report["explanation"])+'</p><h2>Validation findings</h2>'+findings+'<p>Missing fields: '+display(missing)+'</p>'+('<h2>Line items</h2>'+lines if lines else '')+'<p class="note">Translation confidence (self-assessed): '+display(report["translation_confidence"])+'. This is not a calibrated probability. Audit recommendations do not authorize payments.</p></body></html>'
