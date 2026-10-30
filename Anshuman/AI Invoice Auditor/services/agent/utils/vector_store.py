"""
Qdrant Vector Store
===================
Thin, dependency-tolerant wrapper around the Qdrant collection that backs the
agentic RAG pipeline.

Qdrant is a *derived* store: every vector in it is reproducible from the raw
text already persisted in PostgreSQL. Losing the Qdrant volume is therefore a
rebuild, not data loss — `rebuild_from_postgres()` implements exactly that.

Vector size is probed from the live embedding model at first use so the same
code works with Bedrock Titan embeddings and with the deterministic local
fallback embedding.
"""

import os
import uuid
import logging
from typing import Any, Dict, List, Optional

from .llm_client import llm_client
from ..config_loader import load_rules

logger = logging.getLogger("vector_store")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
_NAMESPACE = uuid.UUID("6f1e2d3c-4b5a-4c6d-8e7f-90a1b2c3d4e5")


def _rag_cfg() -> Dict[str, Any]:
    try:
        return (load_rules() or {}).get("rag", {}) or {}
    except Exception:
        return {}


def point_id(invoice_id: str, chunk_index: int) -> str:
    """Deterministic point id so re-indexing an invoice overwrites instead of duplicating."""
    return str(uuid.uuid5(_NAMESPACE, f"{invoice_id}:{chunk_index}"))


class VectorStore:
    def __init__(self):
        self.collection = _rag_cfg().get("collection", "invoice_audit_chunks")
        self._client = None
        self._dim: Optional[int] = None
        self._ready = False
        # In-process fallback so RAG still answers when Qdrant is unreachable.
        self._fallback: Dict[str, Dict[str, Any]] = {}

    # -- connection ------------------------------------------------------------
    def _connect(self):
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=QDRANT_URL, timeout=20)
            client.get_collections()
            self._client = client
            logger.info(f"Qdrant connected ({QDRANT_URL}).")
        except Exception as e:
            logger.warning(f"Qdrant unavailable ({e}). Using in-process vector fallback.")
            self._client = None
        return self._client

    def _vector_size(self) -> int:
        if self._dim is None:
            self._dim = len(llm_client.embed("dimension probe"))
        return self._dim

    def ensure_collection(self) -> bool:
        if self._ready:
            return True
        client = self._connect()
        if client is None:
            return False
        try:
            from qdrant_client.models import Distance, VectorParams, PayloadSchemaType
            size = self._vector_size()
            existing = {c.name for c in client.get_collections().collections}
            if self.collection not in existing:
                client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(size=size, distance=Distance.COSINE),
                )
                logger.info(f"Created Qdrant collection '{self.collection}' (dim={size}).")
            else:
                info = client.get_collection(self.collection)
                current = info.config.params.vectors.size
                if current != size:
                    # Embedding model changed; the index is derived, so rebuild it.
                    logger.warning(
                        f"Collection '{self.collection}' has dim {current} but model emits {size}. Recreating."
                    )
                    client.delete_collection(self.collection)
                    client.create_collection(
                        collection_name=self.collection,
                        vectors_config=VectorParams(size=size, distance=Distance.COSINE),
                    )
            for field in ("invoice_id", "invoice_number", "doc_type"):
                try:
                    client.create_payload_index(self.collection, field, PayloadSchemaType.KEYWORD)
                except Exception:
                    pass  # index already exists
            self._ready = True
            return True
        except Exception as e:
            logger.error(f"Could not prepare Qdrant collection ({e}). Falling back in-process.")
            self._client = None
            return False

    # -- writes ----------------------------------------------------------------
    def upsert(self, records: List[Dict[str, Any]]) -> int:
        """`records` = [{id, vector, payload}]. Returns the number stored."""
        if not records:
            return 0
        if self.ensure_collection():
            try:
                from qdrant_client.models import PointStruct
                self._client.upsert(
                    collection_name=self.collection,
                    points=[
                        PointStruct(id=r["id"], vector=r["vector"], payload=r["payload"])
                        for r in records
                    ],
                    wait=True,
                )
                return len(records)
            except Exception as e:
                logger.error(f"Qdrant upsert failed ({e}). Storing in the in-process fallback.")
                self._client = None
                self._ready = False
        for r in records:
            self._fallback[r["id"]] = r
        return len(records)

    def delete_invoice(self, invoice_id: str) -> None:
        if self.ensure_collection():
            try:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                self._client.delete(
                    collection_name=self.collection,
                    points_selector=Filter(must=[FieldCondition(
                        key="invoice_id", match=MatchValue(value=invoice_id))]),
                )
                return
            except Exception as e:
                logger.warning(f"Qdrant delete failed ({e}).")
        for key in [k for k, v in self._fallback.items()
                    if v["payload"].get("invoice_id") == invoice_id]:
            self._fallback.pop(key, None)

    # -- reads -----------------------------------------------------------------
    def search(self, vector: List[float], *, top_k: int = 12,
               invoice_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.ensure_collection():
            try:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                flt = None
                if invoice_id:
                    flt = Filter(must=[FieldCondition(key="invoice_id",
                                                      match=MatchValue(value=invoice_id))])
                hits = self._client.search(
                    collection_name=self.collection, query_vector=vector,
                    limit=top_k, query_filter=flt, with_payload=True,
                )
                return [{"id": str(h.id), "score": float(h.score), "payload": dict(h.payload or {})}
                        for h in hits]
            except Exception as e:
                logger.error(f"Qdrant search failed ({e}). Using the in-process fallback.")
                self._client = None
                self._ready = False
        return self._fallback_search(vector, top_k=top_k, invoice_id=invoice_id)

    def _fallback_search(self, vector, *, top_k: int, invoice_id: Optional[str]):
        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = sum(x * x for x in a) ** 0.5 or 1.0
            nb = sum(y * y for y in b) ** 0.5 or 1.0
            return dot / (na * nb)

        candidates = [
            r for r in self._fallback.values()
            if not invoice_id or r["payload"].get("invoice_id") == invoice_id
        ]
        scored = [{"id": r["id"], "score": cosine(vector, r["vector"]), "payload": r["payload"]}
                  for r in candidates]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    # -- operations ------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        if self.ensure_collection():
            try:
                info = self._client.get_collection(self.collection)
                return {
                    "backend": "qdrant",
                    "url": QDRANT_URL,
                    "collection": self.collection,
                    "points": info.points_count,
                    "vector_size": info.config.params.vectors.size,
                }
            except Exception as e:
                logger.warning(f"Qdrant stats failed ({e}).")
        return {
            "backend": "in_process_fallback",
            "collection": self.collection,
            "points": len(self._fallback),
            "vector_size": self._dim,
        }

    def health(self) -> Dict[str, Any]:
        return {"reachable": self._connect() is not None, **self.stats()}


vector_store = VectorStore()
