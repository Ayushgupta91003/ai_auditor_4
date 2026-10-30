"""
Parser Node
Extracts structured header fields and line items from translated English invoice text.
Loads extraction prompts from config/prompts.yaml.
"""

import json
import logging
from ..state import InvoiceState
from ...config_loader import load_prompts
from ...utils.llm_client import llm_client

logger = logging.getLogger("parser_node")

def parser_node(state: InvoiceState) -> InvoiceState:
    if state.get("skipped"):
        return state

    text = state.get("translated_text", state.get("raw_extracted_text", ""))
    metadata = state.get("metadata", {})

    prompts = load_prompts()
    p_cfg = prompts.get("parsing", {})
    system_prompt = p_cfg.get("system_prompt", "Extract structured invoice fields into JSON.")
    user_template = p_cfg.get("user_template", "{text}")

    user_prompt = user_template.format(
        text=text,
        metadata=json.dumps(metadata, indent=2) if metadata else "None"
    )

    logger.info("Invoking LLM structured parser...")
    response_text = llm_client.completion(system_prompt, user_prompt)

    try:
        clean_json = response_text.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()

        parsed = json.loads(clean_json)

        state["invoice_number"] = parsed.get("invoice_number")
        state["invoice_date"] = parsed.get("invoice_date")
        state["vendor_id"] = parsed.get("vendor_id")
        state["vendor_name"] = parsed.get("vendor_name")
        state["po_number"] = parsed.get("po_number")
        state["currency"] = parsed.get("currency")
        state["subtotal"] = parsed.get("subtotal")
        state["tax_amount"] = parsed.get("tax_amount")
        state["total_amount"] = parsed.get("total_amount")
        state["line_items"] = parsed.get("line_items", [])
        state["extracted_raw"] = parsed

        # Supplement with email metadata if fields were missing from document body
        if not state["po_number"] and metadata.get("subject"):
            import re
            m = re.search(r"PO-\d+", metadata["subject"])
            if m:
                state["po_number"] = m.group(0)

        if not state["invoice_number"] and metadata.get("subject"):
            import re
            m = re.search(r"INV-[A-Z0-9\-]+", metadata["subject"])
            if m:
                state["invoice_number"] = m.group(0)

        vendor_display = state.get("vendor_name") or state.get("vendor_id") or "None"
        logger.info(
            f"Parsed invoice: No='{state['invoice_number']}', PO='{state['po_number']}', "
            f"Vendor='{vendor_display}', Lines={len(state['line_items'])}"
        )
    except Exception as e:
        logger.error(f"Error parsing structured invoice: {e}. Raw response: {response_text[:120]}")
        state["error"] = f"Parsing error: {e}"

    return state
