"""
Redis Cache
===========
Ephemeral cache for the two operations that are expensive and deterministic:
translation results and LLM completions.

Redis holds no system-of-record data and runs without a volume by design — a
cold cache only costs latency, never correctness. When Redis is unreachable the
cache degrades to a bounded in-process dictionary so the agent keeps working.
"""

import os
import json
import hashlib
import logging
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger("cache")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DEFAULT_TTL = int(os.getenv("CACHE_TTL_SECONDS", "604800"))  # 7 days
MEMORY_MAX_ENTRIES = int(os.getenv("CACHE_MEMORY_MAX", "512"))


def make_key(namespace: str, *parts: Any) -> str:
    """Content-addressed key: identical inputs always resolve to the same slot."""
    blob = "||".join(json.dumps(p, sort_keys=True, default=str) for p in parts)
    return f"invoice-auditor:{namespace}:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


class ResponseCache:
    def __init__(self):
        self._client = None
        self._memory: "OrderedDict[str, str]" = OrderedDict()
        self.hits = 0
        self.misses = 0
        self._connect()

    def _connect(self):
        try:
            import redis
            client = redis.Redis.from_url(REDIS_URL, decode_responses=True,
                                          socket_connect_timeout=3, socket_timeout=3)
            client.ping()
            self._client = client
            logger.info(f"Redis cache connected ({REDIS_URL}).")
        except Exception as e:
            logger.warning(f"Redis unavailable ({e}). Using bounded in-process cache.")
            self._client = None

    @property
    def backend(self) -> str:
        return "redis" if self._client is not None else "in_process"

    def get(self, key: str) -> Optional[Any]:
        raw = None
        if self._client is not None:
            try:
                raw = self._client.get(key)
            except Exception as e:
                logger.warning(f"Redis GET failed ({e}). Falling back to in-process cache.")
                self._client = None
        if raw is None:
            raw = self._memory.get(key)
            if raw is not None:
                self._memory.move_to_end(key)
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def set(self, key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
        try:
            raw = json.dumps(value, default=str)
        except Exception:
            raw = str(value)
        if self._client is not None:
            try:
                self._client.setex(key, ttl, raw)
                return
            except Exception as e:
                logger.warning(f"Redis SET failed ({e}). Falling back to in-process cache.")
                self._client = None
        self._memory[key] = raw
        self._memory.move_to_end(key)
        while len(self._memory) > MEMORY_MAX_ENTRIES:
            self._memory.popitem(last=False)

    def get_or_set(self, key: str, producer, ttl: int = DEFAULT_TTL) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = producer()
        if value is not None:
            self.set(key, value, ttl=ttl)
        return value

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "backend": self.backend,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
            "in_process_entries": len(self._memory),
        }

    def health(self) -> dict:
        ok = False
        if self._client is not None:
            try:
                ok = bool(self._client.ping())
            except Exception:
                ok = False
        return {"reachable": ok, **self.stats()}


response_cache = ResponseCache()
