"""
LLM Client Wrapper
Routes reasoning / translation / parsing / RAG calls and text embeddings through
AWS Bedrock (via LiteLLM) when credentials are configured. When credentials are
absent it falls back to deterministic, evidence-based local handlers:
  - translation: language detection + verbatim passthrough (no fabricated text)
  - parsing: regex extraction from the actual invoice text
  - RAG generation: extractive answer assembled from the retrieved context
  - RAG triad: lexical-overlap metrics computed from query / context / answer
  - embeddings: bag-of-tokens hashed vectors
No invoice-specific content is hard-coded.
"""

import os
import re
import json
import logging
import hashlib
from typing import List

logger = logging.getLogger("llm_client")

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "with", "as", "at", "by", "this", "that", "it", "from",
}


def _tokens(text: str) -> List[str]:
    return [t for t in _WORD_RE.findall((text or "").lower()) if t not in _STOPWORDS]


def _overlap(a: str, b: str) -> float:
    """Fraction of content tokens in `a` that also appear in `b` (0.0-1.0)."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)


def _extract_section(prompt: str, label: str) -> str:
    """Pulls a labelled section out of a rendered prompt template."""
    m = re.search(rf'{re.escape(label)}\s*:?\s*"""(.*?)"""', prompt, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(rf'{re.escape(label)}\s*:?\s*"([^"]*)"', prompt, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


class LLMClient:
    def __init__(self):
        self.aws_access_key = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
        self.aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
        self.aws_region = os.getenv("AWS_REGION_NAME", os.getenv("AWS_DEFAULT_REGION", "us-east-1")).strip()
        self.bedrock_model = os.getenv("BEDROCK_MODEL", "bedrock/amazon.nova-lite-v1:0")
        self.embed_model = os.getenv("EMBED_MODEL", "bedrock/amazon.titan-embed-text-v2:0")
        self.local_embed_dim = int(os.getenv("LOCAL_EMBED_DIM", "384"))

        self.has_aws = bool(
            self.aws_access_key and self.aws_secret_key and
            self.aws_access_key != "your_aws_access_key_here"
        )
        if self.has_aws:
            logger.info(f"AWS credentials detected. Bedrock mode (chat: {self.bedrock_model}, embed: {self.embed_model}).")
        else:
            logger.info("AWS credentials empty. Operating in deterministic local mode (no fabricated content).")

    # --------------------------------------------------------------------------
    # Chat completion
    # --------------------------------------------------------------------------
    def completion(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        if self.has_aws:
            try:
                import litellm
                resp = litellm.completion(
                    model=self.bedrock_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    aws_access_key_id=self.aws_access_key,
                    aws_secret_access_key=self.aws_secret_key,
                    aws_region_name=self.aws_region,
                )
                return resp.choices[0].message.content
            except Exception as e:
                logger.warning(f"Bedrock completion failed ({e}). Using deterministic local handler.")
        return self._local_handler(system_prompt, user_prompt)

    # --------------------------------------------------------------------------
    # Embeddings
    # --------------------------------------------------------------------------
    def embed(self, text: str) -> List[float]:
        text = (text or "").strip() or " "
        if self.has_aws:
            try:
                import litellm
                resp = litellm.embedding(
                    model=self.embed_model,
                    input=[text],
                    aws_access_key_id=self.aws_access_key,
                    aws_secret_access_key=self.aws_secret_key,
                    aws_region_name=self.aws_region,
                )
                vec = resp["data"][0]["embedding"]
                if vec:
                    return [float(x) for x in vec]
            except Exception as e:
                logger.warning(f"Bedrock embedding failed ({e}). Using local embedding.")
        return self._local_embed(text)

    def _local_embed(self, text: str) -> List[float]:
        """Deterministic bag-of-tokens hashed embedding, unit-normalized."""
        dim = self.local_embed_dim
        vec = [0.0] * dim
        for tok in _tokens(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % dim] += 1.0
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm for x in vec]

    # --------------------------------------------------------------------------
    # Deterministic local fallback (no external model)
    # --------------------------------------------------------------------------
    def _local_handler(self, system_prompt: str, user_prompt: str) -> str:
        blob = (system_prompt + " " + user_prompt).lower()
        if "translat" in blob or "multilingual" in blob:
            return self._handle_translation(user_prompt)
        if "parser" in blob or "parse the following" in blob or "structured invoice data" in blob:
            return self._handle_parsing(user_prompt)
        if "rag triad" in blob or "groundedness" in blob:
            return self._handle_rag_triad(user_prompt)
        if "query refinement" in blob or "refined search query" in blob:
            return self._handle_query_refinement(user_prompt)
        if "invoice audit assistant" in blob or "user question" in blob:
            return self._handle_rag_generation(user_prompt)
        return ""

    def _detect_language(self, text: str):
        low = text.lower()
        es = ("factura", "proveedor", "moneda", "cantidad", "precio", "número", "pedido")
        de = ("rechnung", "lieferant", "währung", "menge", "einzelpreis", "bestellnummer", "gesamtbetrag")
        es_hits = sum(1 for w in es if w in low)
        de_hits = sum(1 for w in de if w in low)
        if es_hits >= 2 and es_hits >= de_hits:
            return "es", "Spanish"
        if de_hits >= 2:
            return "de", "German"
        return "en", "English"

    def _handle_translation(self, user_prompt: str) -> str:
        raw = _extract_section(user_prompt, "raw_invoice_text")
        if not raw:
            m = re.search(r"<raw_invoice_text>(.*?)</raw_invoice_text>", user_prompt, re.DOTALL)
            raw = m.group(1).strip() if m else user_prompt.strip()

        lang, lang_name = self._detect_language(raw)
        # Without a translation model we do NOT fabricate English text; we pass the
        # source through verbatim and report zero confidence for non-English input.
        confidence = 1.0 if lang == "en" else 0.0
        return json.dumps({
            "source_language": lang,
            "language_name": lang_name,
            "translated_text": raw,
            "translation_confidence": confidence,
        })

    def _handle_parsing(self, user_prompt: str) -> str:
        text = _extract_section(user_prompt, "invoice_text")
        if not text:
            m = re.search(r"<invoice_text>(.*?)</invoice_text>", user_prompt, re.DOTALL)
            text = m.group(1).strip() if m else user_prompt

        inv_no = self._search(text, r"(?:invoice\s*(?:number|no|#)|rechnungsnummer|(?:n[úu]mero\s+de\s+)?factura)\s*[:#]?\s*([A-Za-z0-9\-]+)")
        inv_date = self._search(text, r"(?:date|datum|fecha)\s*[:#]?\s*(\d{4}-\d{2}-\d{2})")
        po_number = self._search(text, r"(?:purchase\s*order|po\s*(?:ref|number|#)?|bestellnummer|orden\s*de\s*compra)\s*[:#]?\s*(PO-\d+)")
        vendor_id = self._search(text, r"(?:vendor\s*id|lieferantennummer|proveedor)\s*[:#]?\s*(VEND-\d+)")
        vendor_name = self._search(
            text,
            r"(?:vendor\s*(?:name)?|supplier|seller|lieferant|nombre del proveedor)\s*[:#]?\s*([A-Za-z0-9\s\.,&]+?)(?=\n|purchase|po-|total|currency|$)",
        )

        curr = self._search(text, r"(?:currency|w[äa]hrung|moneda)\s*[:#]?\s*([A-Z]{3}|\$|€|£|₹|₫)")
        curr_map = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "₫": "VND"}
        if curr in curr_map:
            curr = curr_map[curr]

        total_amount = self._search_float(text, r"(?:total\s*(?:amount)?|gesamtbetrag|importe\s+total)\s*(?:\([A-Z]+\))?\s*[:#]?\s*([0-9,]+\.?\d*)")
        subtotal = self._search_float(text, r"(?:subtotal|sub-total|zwischensumme)\s*[:#]?\s*([0-9,]+\.?\d*)")
        tax_amount = self._search_float(text, r"(?:tax|vat|iva|mwst|steuer)\s*[:#]?\s*([0-9,]+\.?\d*)")

        line_items = []
        for idx, m in enumerate(re.finditer(
            r"([A-Z]{2,}-\d+)\s+([A-Za-z][A-Za-z\s]+?)\s+(?:Qty:?\s*)?(\d+(?:\.\d+)?)\s+(?:Price:?\s*)?(\d+(?:\.\d+)?)(?:\s+(\d+(?:\.\d+)?))?",
            text,
        )):
            code, desc, qty, price, ltotal = m.groups()
            q_val, p_val = float(qty), float(price)
            t_val = float(ltotal) if ltotal else round(q_val * p_val, 2)
            line_items.append({
                "line_number": idx + 1,
                "item_code": code.strip(),
                "description": desc.strip(),
                "quantity": q_val,
                "unit_price": p_val,
                "line_total": t_val,
            })

        if subtotal is None and line_items:
            subtotal = round(sum(li["line_total"] for li in line_items), 2)

        return json.dumps({
            "invoice_number": inv_no,
            "invoice_date": inv_date,
            "vendor_id": vendor_id,
            "vendor_name": vendor_name,
            "po_number": po_number,
            "currency": curr,
            "subtotal": subtotal,
            "tax_amount": tax_amount if tax_amount is not None else 0.0,
            "total_amount": total_amount if total_amount is not None else subtotal,
            "line_items": line_items,
            "notes": None,
        })

    def _handle_rag_triad(self, user_prompt: str) -> str:
        query = _extract_section(user_prompt, "User Query")
        context = _extract_section(user_prompt, "Retrieved Context")
        answer = _extract_section(user_prompt, "Generated Answer")

        context_relevance = round(_overlap(query, context), 3)
        groundedness = round(_overlap(answer, context), 3)
        answer_relevance = round(_overlap(query, answer), 3)
        avg = round((context_relevance + groundedness + answer_relevance) / 3.0, 3)
        return json.dumps({
            "context_relevance": context_relevance,
            "groundedness": groundedness,
            "answer_relevance": answer_relevance,
            "average_score": avg,
            "passed": avg > 0.70,
            "critique": (
                f"Lexical evaluation: context/query overlap={context_relevance}, "
                f"answer/context grounding={groundedness}, answer/query relevance={answer_relevance}."
            ),
        })

    def _handle_query_refinement(self, user_prompt: str) -> str:
        original = self._search(user_prompt, r'Original Query:\s*"([^"]*)"') or ""
        keywords = [t for t in _tokens(original) if len(t) > 2]
        ids = re.findall(r"(?:INV|PO|VEND|SKU)-[A-Z0-9\-]+", user_prompt, re.IGNORECASE)
        refined = " ".join(dict.fromkeys(ids + keywords))
        return refined or original

    def _handle_rag_generation(self, user_prompt: str) -> str:
        context = _extract_section(user_prompt, "Context retrieved from invoice audit records")
        if not context:
            context = _extract_section(user_prompt, "Context")
        query = self._search(user_prompt, r'User Question:\s*"([^"]*)"') or ""
        if not context.strip():
            return "The information is not available in the audit records."

        q_tokens = set(_tokens(query))
        lines = [ln.strip() for ln in context.splitlines() if ln.strip()]
        scored = sorted(
            lines,
            key=lambda ln: len(q_tokens & set(_tokens(ln))),
            reverse=True,
        )
        top = [ln for ln in scored if q_tokens & set(_tokens(ln))][:4] or lines[:3]
        return "Based on the retrieved audit records:\n" + "\n".join(f"- {ln}" for ln in top)

    # --------------------------------------------------------------------------
    @staticmethod
    def _search(text: str, pattern: str):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    @staticmethod
    def _search_float(text: str, pattern: str):
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None


llm_client = LLMClient()
