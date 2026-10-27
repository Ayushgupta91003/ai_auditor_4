"""Pure correction logic: validate a copy and leave original extraction unchanged."""
from copy import deepcopy
import json
from agent.models import Invoice

def apply_feedback(original, feedback):
    if original is None: raise ValueError("Invoice has not been extracted yet")
    data=deepcopy(original)
    for change in feedback:
        target=target_for(data,change.get("line_number"))
        field=change["field_name"]
        if field not in target or field in ("line_items","line_number","extra_fields"):
            raise ValueError("Unsupported correction field")
        target[field]=json.loads(change["corrected_value"])
    return Invoice.model_validate(data)

def target_for(data,line_number):
    if line_number is None: return data
    matches=[x for x in data["line_items"] if x["line_number"]==line_number]
    if len(matches)!=1: raise ValueError("Line number is missing or ambiguous")
    return matches[0]

def prepare_correction(invoice,correction):
    data=invoice.model_dump(mode="json")
    target=target_for(data,correction.line_number)
    if correction.field not in target or correction.field in ("line_items","line_number","extra_fields"):
        raise ValueError("Unsupported correction field")
    original=target[correction.field]
    target[correction.field]=correction.value
    checked=Invoice.model_validate(data).model_dump(mode="json")
    corrected=target_for(checked,correction.line_number)[correction.field]
    return json.dumps(original),json.dumps(corrected)
