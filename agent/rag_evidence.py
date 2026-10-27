"""Index verified report fields instead of recursively grounding on generated prose."""
import json
FIELDS=("invoice_id","version","recommendation","findings","missing_fields","translation_confidence")
def report_evidence(report,effective_invoice):
    data={key:report[key] for key in FIELDS if key in report}
    data["invoice"]=effective_invoice
    data["evidence_note"]="Effective values in this report supersede conflicting original extraction values."
    return json.dumps(data,ensure_ascii=False)
