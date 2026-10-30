"""
Translation Node
Detects source language and translates non-English invoice text to English.
Uses prompts from config/prompts.yaml.
CRITICAL CONSTRAINT: Redis in-memory caching is EXPLICITLY DISABLED for translated text.
Results are written directly to state and persisted in PostgreSQL.
"""

import json
import logging
from ..state import InvoiceState
from ...config_loader import load_prompts
from ...utils.llm_client import llm_client

logger = logging.getLogger("translator_node")

def translator_node(state: InvoiceState) -> InvoiceState:
    if state.get("skipped"):
        return state

    raw_text = state.get("raw_extracted_text", "")
    metadata = state.get("metadata", {})
    hint_lang = metadata.get("language")

    prompts = load_prompts()
    t_cfg = prompts.get("translation", {})
    system_prompt = t_cfg.get("system_prompt", "Translate non-English invoices to English.")
    user_template = t_cfg.get("user_template", "{raw_text}")

    # Format user prompt
    user_prompt = user_template.format(raw_text=raw_text)

    # Detect English quickly if metadata or simple heuristics confirm English
    lower_text = raw_text.lower()
    is_clearly_english = (
        hint_lang == "en" and
        ("invoice" in lower_text or "total" in lower_text) and
        not any(w in lower_text for w in ["factura", "moneda", "rechnung", "währung", "lieferant"])
    )

    if is_clearly_english:
        state["source_language"] = "en"
        state["language_name"] = "English"
        state["translated_text"] = raw_text
        state["translation_confidence"] = 1.00
        logger.info("Invoice detected as English. Translation bypassed (confidence: 1.00).")
        return state

    # Invoke LLM translation via prompt
    logger.info("Invoking LLM translation agent...")
    response_text = llm_client.completion(system_prompt, user_prompt)

    try:
        # Extract JSON from response if surrounded by markdown code blocks
        clean_json = response_text.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()

        data = json.loads(clean_json)
        state["source_language"] = data.get("source_language", "en")
        state["language_name"] = data.get("language_name", "English")
        state["translated_text"] = data.get("translated_text", raw_text)
        state["translation_confidence"] = float(data.get("translation_confidence", 0.95))
        logger.info(
            f"Translated invoice from {state['language_name']} ({state['source_language']}) "
            f"with confidence {state['translation_confidence']:.2f}"
        )
    except Exception as e:
        logger.error(f"Failed to parse translation LLM output: {e}. Raw: {response_text[:100]}")
        state["source_language"] = hint_lang or "unknown"
        state["language_name"] = "Unknown"
        state["translated_text"] = raw_text
        state["translation_confidence"] = 0.50

    return state
