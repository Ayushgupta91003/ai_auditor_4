"""
RAG Node & Query Pipeline with RAG Triad Reflection
Addresses requirements:
  - 3.6: Indexing, Retrieval, Augmentation, Generation, and Reflection (Triad average > 0.7, max 3 retries).
  - 6.3: Qdrant payload (invoice_id, chunk_text, source_type, vendor, language).
  - 6.4: Redis caching for LLM responses (llm:{sha256(prompt)}).
Embeddings are produced by the LLM client (AWS Bedrock Titan when configured,
deterministic local vectors otherwise); the Qdrant collection dimension is
detected from the embedding model at startup.
"""

import os
import json
import hashlib
import logging
from typing import Dict, Any, List, Optional, Tuple
from ..state import InvoiceState
from ...config_loader import load_prompts
from ...utils.llm_client import llm_client

logger = logging.getLogger("rag_node")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
COLLECTION_NAME = "invoices"

class RedisCache:
    def __init__(self):
        self.client = None
        self._local_cache = {}
        try:
            import redis
            self.client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            self.client.ping()
            logger.info("Connected to Redis ephemeral cache.")
        except Exception as e:
            logger.warning(f"Redis cache unavailable ({e}). Using in-memory fallback for LLM responses.")
            self.client = None

    def get(self, key: str) -> Optional[str]:
        if self.client:
            try:
                return self.client.get(key)
            except Exception:
                pass
        return self._local_cache.get(key)

    def set(self, key: str, value: str, ex: int = 3600):
        if self.client:
            try:
                self.client.set(key, value, ex=ex)
                return
            except Exception:
                pass
        self._local_cache[key] = value

redis_cache = RedisCache()

class VectorStore:
    def __init__(self):
        self.qdrant_client = None
        self._in_memory_docs = []
        # Detect embedding dimension from the active embedding model.
        try:
            self.vector_size = len(llm_client.embed("dimension probe")) or 384
        except Exception:
            self.vector_size = 384
        try:
            from qdrant_client import QdrantClient
            self.qdrant_client = QdrantClient(url=QDRANT_URL, timeout=3)
            # Ensure collection exists with the correct dimension
            collections = [c.name for c in self.qdrant_client.get_collections().collections]
            if COLLECTION_NAME not in collections:
                from qdrant_client.models import VectorParams, Distance
                self.qdrant_client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE)
                )
            logger.info(f"Connected to Qdrant collection: {COLLECTION_NAME} (dim={self.vector_size})")
        except Exception as e:
            logger.warning(f"Qdrant unavailable ({e}). Using in-memory vector store fallback.")
            self.qdrant_client = None

    def _embed(self, text: str) -> List[float]:
        # Real embeddings via Bedrock (Titan) when configured; deterministic local fallback otherwise.
        return llm_client.embed(text)

    def upsert(self, doc_id: str, text: str, payload: Dict[str, Any]):
        vector = self._embed(text)
        if self.qdrant_client:
            try:
                from qdrant_client.models import PointStruct
                import uuid
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))
                self.qdrant_client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=[PointStruct(id=point_id, vector=vector, payload=payload)]
                )
                return
            except Exception as e:
                logger.error(f"Error upserting to Qdrant: {e}")

        # In-memory store
        self._in_memory_docs.append({
            "id": doc_id,
            "text": text,
            "vector": vector,
            "payload": payload
        })

    def search(self, query: str, invoice_id: Optional[str] = None, top_k: int = 4) -> List[Dict[str, Any]]:
        q_vec = self._embed(query)
        if self.qdrant_client:
            try:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                q_filter = None
                if invoice_id:
                    q_filter = Filter(
                        must=[FieldCondition(key="invoice_id", match=MatchValue(value=invoice_id))]
                    )
                # qdrant-client >= 1.12 removed .search(); use .query_points().
                response = self.qdrant_client.query_points(
                    collection_name=COLLECTION_NAME,
                    query=q_vec,
                    query_filter=q_filter,
                    limit=top_k,
                    with_payload=True
                )
                results = response.points
                return [
                    {
                        "chunk_text": hit.payload.get("chunk_text"),
                        "invoice_id": hit.payload.get("invoice_id"),
                        "source_type": hit.payload.get("source_type"),
                        "score": hit.score
                    }
                    for hit in results
                ]
            except Exception as e:
                logger.error(f"Qdrant search error: {e}")

        # In-memory cosine search
        scored = []
        for doc in self._in_memory_docs:
            if invoice_id and doc["payload"].get("invoice_id") != invoice_id:
                continue
            dot = sum(a * b for a, b in zip(q_vec, doc["vector"]))
            # Lexical boost
            query_terms = query.lower().split()
            overlap = sum(1 for term in query_terms if term in doc["text"].lower())
            final_score = dot + (overlap * 0.1)
            scored.append((final_score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "chunk_text": d[1]["payload"].get("chunk_text", d[1]["text"]),
                "invoice_id": d[1]["payload"].get("invoice_id"),
                "source_type": d[1]["payload"].get("source_type"),
                "score": d[0]
            }
            for d in scored[:top_k]
        ]

vector_store = VectorStore()

# ------------------------------------------------------------------------------
# 1. Indexing Agent (called in LangGraph pipeline)
# ------------------------------------------------------------------------------
def indexing_node(state: InvoiceState) -> InvoiceState:
    if state.get("skipped"):
        return state

    invoice_id = state.get("invoice_id", "unknown")
    vendor = state.get("vendor_name", "unknown")
    lang = state.get("source_language", "en")

    # Chunk 1: Invoice Header & Line Items Summary
    chunk_invoice = (
        f"Invoice Number: {state.get('invoice_number')}\n"
        f"PO Number: {state.get('po_number')}\n"
        f"Vendor: {vendor} ({state.get('vendor_id')})\n"
        f"Currency: {state.get('currency')}\n"
        f"Total Amount: {state.get('total_amount')}\n"
        f"Line Items: {json.dumps(state.get('line_items', []))}"
    )
    vector_store.upsert(
        doc_id=f"{invoice_id}_invoice",
        text=chunk_invoice,
        payload={
            "invoice_id": invoice_id,
            "chunk_text": chunk_invoice,
            "source_type": "invoice_text",
            "vendor": vendor,
            "language": lang
        }
    )

    # Chunk 2: Validation & Discrepancy Report Summary
    chunk_report = (
        f"Invoice Audit Report for {state.get('invoice_number')} (PO: {state.get('po_number')}):\n"
        f"Validation Status: {state.get('validation_status')}\n"
        f"Recommendation: {state.get('recommendation')}\n"
        f"Translation Confidence: {state.get('translation_confidence')}\n"
        f"Discrepancies: {json.dumps(state.get('discrepancies', []))}\n"
        f"Data Errors: {json.dumps(state.get('data_validation_errors', []))}"
    )
    vector_store.upsert(
        doc_id=f"{invoice_id}_report",
        text=chunk_report,
        payload={
            "invoice_id": invoice_id,
            "chunk_text": chunk_report,
            "source_type": "report_text",
            "vendor": vendor,
            "language": lang
        }
    )

    state["rag_indexed"] = True
    logger.info(f"Indexed invoice {invoice_id} in vector store.")
    return state

# ------------------------------------------------------------------------------
# 2. RAG Query Engine with Reflection & Retry Loop
# ------------------------------------------------------------------------------
def query_rag_with_triad(query: str, invoice_id: Optional[str] = None, max_retries: int = 3) -> Dict[str, Any]:
    prompts = load_prompts()
    gen_cfg = prompts.get("rag_generation", {})
    gen_sys = gen_cfg.get("system_prompt", "Answer questions based on retrieved invoice records.")
    gen_user_template = gen_cfg.get("user_template", "Context: {context}\nQuestion: {query}")

    ref_cfg = prompts.get("rag_reflection", {})
    ref_sys = ref_cfg.get("system_prompt", "Evaluate RAG Triad scores.")
    ref_user_template = ref_cfg.get("user_template", "{query}\n{context}\n{answer}")

    curr_query = query
    attempt = 0
    triad_history = []
    final_answer = ""
    cached = False
    hits = []

    while attempt < max_retries:
        attempt += 1
        logger.info(f"RAG attempt {attempt}/{max_retries} for query: '{curr_query}'")

        # 1. Retrieval
        hits = vector_store.search(curr_query, invoice_id=invoice_id, top_k=3)
        context_text = "\n\n".join([f"[{h['source_type']}]: {h['chunk_text']}" for h in hits])

        if not context_text:
            context_text = "No direct chunks found in vector database."

        # 2. Check LLM Cache in Redis
        prompt_hash = hashlib.sha256(f"{curr_query}:{context_text}".encode()).hexdigest()
        cache_key = f"llm:{prompt_hash}"
        cached_resp = redis_cache.get(cache_key)

        if cached_resp:
            logger.info("Retrieved answer from Redis LLM cache.")
            final_answer = cached_resp
            cached = True
        else:
            # 3. Generation
            user_prompt = gen_user_template.format(context=context_text, query=curr_query)
            final_answer = llm_client.completion(gen_sys, user_prompt)
            # Cache in Redis
            redis_cache.set(cache_key, final_answer, ex=3600)

        # 4. Reflection (RAG Triad)
        eval_prompt = ref_user_template.format(query=curr_query, context=context_text, answer=final_answer)
        eval_resp = llm_client.completion(ref_sys, eval_prompt)

        try:
            clean_eval = eval_resp.strip()
            if "```json" in clean_eval:
                clean_eval = clean_eval.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_eval:
                clean_eval = clean_eval.split("```")[1].split("```")[0].strip()
            eval_data = json.loads(clean_eval)
        except Exception:
            eval_data = {
                "context_relevance": 0.0,
                "groundedness": 0.0,
                "answer_relevance": 0.0,
                "average_score": 0.0,
                "passed": False,
                "critique": "Evaluator response could not be parsed."
            }

        avg_score = eval_data.get("average_score", 0.0)
        triad_history.append(eval_data)
        logger.info(f"RAG Triad evaluation: Avg Score = {avg_score:.3f} (Passed: {avg_score > 0.7})")

        # Threshold check: > 0.70
        if avg_score > 0.70:
            return {
                "query": query,
                "answer": final_answer,
                "triad_scores": eval_data,
                "retries": attempt,
                "cached": cached,
                "context_chunks": hits
            }

        # Query refinement if score <= 0.7 and retries remain
        refine_cfg = prompts.get("rag_query_refinement", {})
        refine_sys = refine_cfg.get("system_prompt", "Refine retrieval query.")
        refine_user = refine_cfg.get("user_template", "{query}\n{critique}").format(
            query=curr_query,
            critique=eval_data.get("critique", "Score below 0.7")
        )
        curr_query = llm_client.completion(refine_sys, refine_user).strip() or curr_query

    return {
        "query": query,
        "answer": final_answer,
        "triad_scores": triad_history[-1] if triad_history else {},
        "retries": attempt,
        "cached": cached,
        "context_chunks": hits
    }
