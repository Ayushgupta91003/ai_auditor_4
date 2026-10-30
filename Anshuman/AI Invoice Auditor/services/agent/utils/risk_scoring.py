"""
Risk Scoring for the Human-in-the-Loop review gate.
Converts validation results (discrepancies, data errors, translation confidence)
into a single weighted risk score and a routing decision:
  - 'auto_approved'  -> safe to index into the vector store automatically
  - 'pending_review' -> hold for a human to approve/reject before indexing
"""

from typing import Dict, Any, List, Tuple

DEFAULT_SEVERITY_WEIGHTS = {"CRITICAL": 1.00, "ERROR": 0.60, "WARNING": 0.30, "INFO": 0.10}
DEFAULT_WEIGHTS = {"data_error": 0.40, "low_translation_confidence": 0.30}
DEFAULT_THRESHOLD = 0.30
DEFAULT_LOW_CONFIDENCE = 0.75
DEFAULT_HARD_BLOCKS = ["reject_recommendation", "critical_discrepancy", "invalid_currency", "missing_header_field"]


def compute_risk(state: Dict[str, Any], rules: Dict[str, Any]) -> Tuple[float, str, List[str]]:
    """Returns (risk_score, review_status, reasons)."""
    cfg = rules.get("risk_scoring", {}) or {}
    sev_weights = {**DEFAULT_SEVERITY_WEIGHTS, **(cfg.get("severity_weights") or {})}
    weights = {**DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}
    threshold = float(cfg.get("auto_approve_threshold", DEFAULT_THRESHOLD))
    low_conf = float(cfg.get("low_translation_confidence", DEFAULT_LOW_CONFIDENCE))
    hard_blocks = set(cfg.get("hard_blocks") or DEFAULT_HARD_BLOCKS)

    discrepancies: List[Dict[str, Any]] = state.get("discrepancies", []) or []
    data_errors: List[str] = state.get("data_validation_errors", []) or []
    recommendation = (state.get("recommendation") or "").lower()
    translation_confidence = float(state.get("translation_confidence") or 1.0)

    score = 0.0
    reasons: List[str] = []
    hard_block = False

    for d in discrepancies:
        sev = str(d.get("severity", "WARNING")).upper()
        w = float(sev_weights.get(sev, DEFAULT_SEVERITY_WEIGHTS["WARNING"]))
        score += w
        field = str(d.get("field_name", ""))
        reasons.append(f"{sev} discrepancy on '{field}' (+{w:.2f})")
        if sev == "CRITICAL" and "critical_discrepancy" in hard_blocks:
            hard_block = True
        if "currency" in field.lower() and "invalid_currency" in hard_blocks:
            hard_block = True

    if data_errors:
        w = float(weights.get("data_error", DEFAULT_WEIGHTS["data_error"]))
        score += w * len(data_errors)
        reasons.append(f"{len(data_errors)} data-validation error(s) (+{w * len(data_errors):.2f})")
        if "missing_header_field" in hard_blocks and any("Missing mandatory header" in e for e in data_errors):
            hard_block = True
        if "invalid_currency" in hard_blocks and any("Currency" in e and "accepted list" in e for e in data_errors):
            hard_block = True

    if translation_confidence < low_conf:
        w = float(weights.get("low_translation_confidence", DEFAULT_WEIGHTS["low_translation_confidence"]))
        score += w
        reasons.append(f"Low translation confidence {translation_confidence:.2f} (+{w:.2f})")

    if recommendation == "reject" and "reject_recommendation" in hard_blocks:
        hard_block = True
        reasons.append("Reporter recommended REJECT (hard block)")

    score = round(score, 3)

    if hard_block:
        review_status = "pending_review"
    elif score <= threshold:
        review_status = "auto_approved"
    else:
        review_status = "pending_review"

    if not reasons:
        reasons.append("No discrepancies or errors detected.")

    return score, review_status, reasons
