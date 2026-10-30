"""
RAG Tools
=========
The five tools owned by the agentic RAG roles. They are deliberately thin and
stateless: the agents in `services/agent/rag/agents.py` decide *when* to call
them and what to do with the result.

  Vector-Indexer Tool       -> Indexing Agent
  Semantic-Retriever Tool   -> Retrieval Agent
  Chunk-Ranker Tool         -> Augmentation Agent
  Response-Synthesizer Tool -> Generation Agent
  RAG-Evaluator Tool        -> Reflection Agent
"""

import re
import json
import logging
from typing import Any, Dict, List, Optional

from .registry import registry
from ..config_loader import load_rules, load_prompts
from ..utils.cache import response_cache, make_key
from ..utils.guardrails import guardrails
from ..utils.llm_client import llm_client
from ..utils.vector_store import vector_store, point_id

logger = logging.getLogger("tools.rag")

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
              "are", "was", "were", "be", "with", "as", "at", "by", "this", "that",
              "it", "from", "what", "which", "how", "who", "when", "show", "me"}


def _rag_cfg() -> Dict[str, Any]:
    return (load_rules() or {}).get("rag", {}) or {}


def _tokens(text: str) -> set:
    return {t for t in _WORD_RE.findall((text or "").lower()) if t not in _STOPWORDS and len(t) > 2}


def chunk_text(text: str, *, size: int, overlap: int) -> List[str]:
    """Paragraph-aware chunking so invoice blocks stay intact where possible."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buffer = ""
    for para in paragraphs:
        if len(buffer) + len(para) + 2 <= size:
            buffer = f"{buffer}\n\n{para}".strip()
            continue
        if buffer:
            chunks.append(buffer)
        while len(para) > size:
            chunks.append(para[:size])
            para = para[max(0, size - overlap):]
        buffer = para
    if buffer:
        chunks.append(buffer)

    # Re-introduce overlap between adjacent chunks so facts on a boundary survive.
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:]):
            overlapped.append((prev[-overlap:] + "\n" + cur).strip())
        chunks = overlapped
    return chunks


# ==============================================================================
# 1. Vector-Indexer Tool
# ==============================================================================
@registry.tool(
    name="vector_indexer",
    description=(
        "Converts invoice text and its audit report into overlapping chunks, embeds them and "
        "upserts them into the Qdrant collection with deterministic point ids, so re-indexing an "
        "invoice replaces its vectors instead of duplicating them."
    ),
    agent="Indexing Agent",
    read_only=False,
    input_schema={
        "type": "object",
        "properties": {
            "invoice_id": {"type": "string"},
            "documents": {
                "type": "array",
                "description": "Text documents to index.",
                "items": {
                    "type": "object",
                    "properties": {"doc_type": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["text"],
                },
            },
            "metadata": {"type": "object", "description": "Payload attached to every chunk."},
        },
        "required": ["invoice_id", "documents"],
        "additionalProperties": False,
    },
)
def vector_indexer(invoice_id: str, documents: List[Dict[str, Any]],
                   metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = _rag_cfg()
    size = int(cfg.get("chunk_size", 900))
    overlap = int(cfg.get("chunk_overlap", 150))
    metadata = metadata or {}

    records: List[Dict[str, Any]] = []
    index = 0
    for doc in documents:
        doc_type = doc.get("doc_type", "invoice_text")
        for chunk in chunk_text(doc.get("text", ""), size=size, overlap=overlap):
            records.append({
                "id": point_id(invoice_id, index),
                "vector": llm_client.embed(chunk),
                "payload": {**metadata, "invoice_id": invoice_id, "doc_type": doc_type,
                            "chunk_index": index, "text": chunk},
            })
            index += 1

    if not records:
        return {"invoice_id": invoice_id, "chunks_indexed": 0, "indexed": False,
                "reason": "no_text_to_index"}

    # Drop stale vectors first: an invoice re-indexed after a correction must not
    # keep chunks from the superseded extraction.
    vector_store.delete_invoice(invoice_id)
    stored = vector_store.upsert(records)
    return {"invoice_id": invoice_id, "chunks_indexed": stored, "indexed": stored > 0,
            "collection": vector_store.collection}


# ==============================================================================
# 2. Semantic-Retriever Tool
# ==============================================================================
@registry.tool(
    name="semantic_retriever",
    description=(
        "Embeds a user query and performs vector similarity search over the invoice chunk "
        "collection, optionally filtered to a single invoice."
    ),
    agent="Retrieval Agent",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
            "invoice_id": {"type": "string", "description": "Restrict retrieval to one invoice."},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)
def semantic_retriever(query: str, top_k: Optional[int] = None,
                       invoice_id: Optional[str] = None) -> Dict[str, Any]:
    cfg = _rag_cfg()
    k = int(top_k or cfg.get("top_k", 12))
    hits = vector_store.search(llm_client.embed(query), top_k=k, invoice_id=invoice_id)
    chunks = [{
        "id": h["id"],
        "score": round(h["score"], 4),
        "text": h["payload"].get("text", ""),
        "invoice_id": h["payload"].get("invoice_id"),
        "invoice_number": h["payload"].get("invoice_number"),
        "doc_type": h["payload"].get("doc_type"),
    } for h in hits]
    return {"query": query, "invoice_filter": invoice_id, "retrieved": len(chunks), "chunks": chunks}


# ==============================================================================
# 3. Chunk-Ranker Tool
# ==============================================================================
@registry.tool(
    name="chunk_ranker",
    description=(
        "Re-ranks retrieved chunks with a hybrid score that combines vector similarity with "
        "lexical overlap against the query, removes near-duplicates, and keeps the top N to "
        "assemble a focused context window."
    ),
    agent="Augmentation Agent",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "chunks": {"type": "array", "items": {"type": "object"}},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["query", "chunks"],
        "additionalProperties": False,
    },
)
def chunk_ranker(query: str, chunks: List[Dict[str, Any]], top_n: Optional[int] = None) -> Dict[str, Any]:
    cfg = _rag_cfg()
    n = int(top_n or cfg.get("rerank_top_n", 5))
    q_tokens = _tokens(query)

    ranked: List[Dict[str, Any]] = []
    for chunk in chunks:
        c_tokens = _tokens(chunk.get("text", ""))
        lexical = len(q_tokens & c_tokens) / len(q_tokens) if q_tokens else 0.0
        # Exact identifier hits (INV-/PO-/VEND-/SKU-) are what auditors ask about.
        ids = set(re.findall(r"(?:INV|PO|VEND|SKU)[-_][A-Z0-9\-_]+", query, re.IGNORECASE))
        id_hit = 1.0 if ids and any(i.lower() in chunk.get("text", "").lower() for i in ids) else 0.0
        vector_score = float(chunk.get("score", 0.0))
        rerank = round(0.55 * vector_score + 0.30 * lexical + 0.15 * id_hit, 4)
        ranked.append({**chunk, "lexical_overlap": round(lexical, 4),
                       "identifier_match": id_hit, "rerank_score": rerank})

    ranked.sort(key=lambda c: c["rerank_score"], reverse=True)

    deduped: List[Dict[str, Any]] = []
    seen: List[set] = []
    for chunk in ranked:
        tokens = _tokens(chunk.get("text", ""))
        if any(tokens and len(tokens & s) / len(tokens) > 0.9 for s in seen):
            continue
        seen.append(tokens)
        deduped.append(chunk)
        if len(deduped) >= n:
            break

    context = "\n\n---\n\n".join(
        f"[invoice={c.get('invoice_number') or c.get('invoice_id')} source={c.get('doc_type')} "
        f"score={c['rerank_score']}]\n{c.get('text', '')}" for c in deduped
    )
    return {"top_n": n, "ranked_chunks": deduped, "context": context,
            "context_characters": len(context)}


# ==============================================================================
# 4. Response-Synthesizer Tool
# ==============================================================================
@registry.tool(
    name="response_synthesizer",
    description=(
        "Generates a natural-language answer from the assembled context and the user query, "
        "using the rag_generation prompt template through LiteLLM. Identical (query, context) "
        "pairs are served from the Redis cache instead of hitting the model again."
    ),
    agent="Generation Agent",
    guardrails=["pii_redaction", "groundedness_floor", "financial_disclaimer"],
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "context": {"type": "string"},
            "use_cache": {"type": "boolean", "default": True},
        },
        "required": ["query", "context"],
        "additionalProperties": False,
    },
)
def response_synthesizer(query: str, context: str, use_cache: bool = True) -> Dict[str, Any]:
    prompts = load_prompts().get("rag_generation", {})
    system_prompt = prompts.get("system_prompt", "You are the AI Invoice Audit Assistant.")
    user_prompt = prompts.get("user_template", "{context}\n{query}").format(context=context, query=query)

    key = make_key("rag_answer", llm_client.bedrock_model, query, context)
    cached_payload = response_cache.get(key) if use_cache else None

    if cached_payload is not None:
        answer = cached_payload.get("answer", "")
        cached = True
    else:
        answer = llm_client.completion(system_prompt, user_prompt, temperature=0.0) or ""
        cached = False
        if use_cache:
            response_cache.set(key, {"answer": answer})

    scan = guardrails.scan_answer(answer, context=context, query=query)
    return {
        "answer": scan.text,
        "raw_answer": answer,
        "cached": cached,
        "guardrail_allowed": scan.allowed,
        "guardrail_findings": scan.findings,
    }


# ==============================================================================
# 5. RAG-Evaluator Tool
# ==============================================================================
@registry.tool(
    name="rag_evaluator",
    description=(
        "Scores a RAG interaction on the RAG Triad — context relevance, groundedness and answer "
        "relevance — and returns the average together with a pass/fail against the configured "
        "threshold and a critique the Reflection Agent can use to refine the query."
    ),
    agent="Reflection Agent",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "context": {"type": "string"},
            "answer": {"type": "string"},
        },
        "required": ["query", "context", "answer"],
        "additionalProperties": False,
    },
)
def rag_evaluator(query: str, context: str, answer: str) -> Dict[str, Any]:
    threshold = float(_rag_cfg().get("triad_pass_threshold", 0.70))
    prompts = load_prompts().get("rag_reflection", {})
    system_prompt = prompts.get("system_prompt", "You evaluate RAG answers on the RAG Triad.")
    user_prompt = prompts.get("user_template", "{query}\n{context}\n{answer}").format(
        query=query, context=context, answer=answer)

    raw = llm_client.completion(system_prompt, user_prompt, temperature=0.0)
    metrics = _parse_triad(raw)

    if metrics is None:
        # The evaluator must still produce a verdict, so fall back to lexical scoring.
        metrics = _lexical_triad(query, context, answer)
        metrics["critique"] = "Model evaluation unavailable; scored by lexical overlap. " + metrics["critique"]

    metrics["average_score"] = round(
        (metrics["context_relevance"] + metrics["groundedness"] + metrics["answer_relevance"]) / 3.0, 3)
    metrics["threshold"] = threshold
    metrics["passed"] = metrics["average_score"] > threshold
    return metrics


def _parse_triad(raw: str) -> Optional[Dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return None
    if "```" in text:
        text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1]
    try:
        data = json.loads(text)
        return {
            "context_relevance": float(data.get("context_relevance", 0.0)),
            "groundedness": float(data.get("groundedness", 0.0)),
            "answer_relevance": float(data.get("answer_relevance", 0.0)),
            "critique": str(data.get("critique", "")),
        }
    except Exception:
        return None


def _lexical_triad(query: str, context: str, answer: str) -> Dict[str, Any]:
    def overlap(a: str, b: str) -> float:
        ta, tb = _tokens(a), _tokens(b)
        return round(len(ta & tb) / len(ta), 3) if ta else 0.0

    cr, gr, ar = overlap(query, context), overlap(answer, context), overlap(query, answer)
    return {
        "context_relevance": cr, "groundedness": gr, "answer_relevance": ar,
        "critique": (f"context/query overlap={cr}, answer/context grounding={gr}, "
                     f"answer/query relevance={ar}."),
    }


@registry.tool(
    name="query_refiner",
    description=("Rewrites a user query into a retrieval-optimised form using the evaluator's "
                 "critique, so the Reflection Agent's retry retrieves better chunks."),
    agent="Reflection Agent",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}, "critique": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    },
)
def query_refiner(query: str, critique: str = "") -> Dict[str, Any]:
    prompts = load_prompts().get("rag_query_refinement", {})
    system_prompt = prompts.get("system_prompt", "You refine vector search queries.")
    user_prompt = prompts.get("user_template", "{query}\n{critique}").format(query=query, critique=critique)
    refined = (llm_client.completion(system_prompt, user_prompt, temperature=0.0) or "").strip()
    refined = refined.strip('"').splitlines()[0] if refined else ""
    return {"original_query": query, "refined_query": refined or query, "changed": bool(refined) and refined != query}
