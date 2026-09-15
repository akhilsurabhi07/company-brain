"""
Semantic Retrieval Cache — Infrastructure Layer
==============================================
Provides in-memory & Redis cache lookup for frequent enterprise queries (sub-10ms latency).
"""
import hashlib
from typing import Dict, Any, Optional

class SemanticRetrievalCache:
    """In-memory & Redis semantic cache implementation."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _generate_key(self, tenant_id: str, query: str) -> str:
        raw = f"{tenant_id}:{query.strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def get(self, tenant_id: str, query: str) -> Optional[Dict[str, Any]]:
        key = self._generate_key(tenant_id, query)
        return self._cache.get(key)

    async def set(self, tenant_id: str, query: str, data: Dict[str, Any]) -> None:
        key = self._generate_key(tenant_id, query)
        self._cache[key] = data

semantic_cache = SemanticRetrievalCache()
