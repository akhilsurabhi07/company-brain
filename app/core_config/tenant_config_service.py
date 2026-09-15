"""
Tenant Feature Flags & Configuration Service
============================================
Provides tenant-scoped feature flags and dynamic configuration settings.

Real DB-backed persistence (tenants.settings JSONB) with an in-memory cache. The
existing get_* methods stay synchronous and unchanged in signature deliberately —
they're called from the synchronous Phase 1 chunking/embedding hot path
(semantic_chunker.py, embedding_orchestrator.py), which this fix does not touch or
redesign. Real persistence is achieved instead by pre-loading a tenant's config into
the cache (via the async load_tenant_config) before that hot path runs — see
ingestion_router.py's run_tenant_ingestion_pipeline.

Previously `_tenant_configs` had no setter at all — there was no way to ever populate
it, so every call silently fell through to hardcoded defaults regardless of intent.
"""
from typing import Dict, Any
from sqlalchemy import text
from app.core_config.chunking_config import get_chunking_policy
from app.core_config.model_capability_registry import get_model_capability, ModelCapability

_DEFAULT_FEATURE_FLAGS = {
    "parent_child_rag": True,
    "rrf_hybrid_search": True,
    "tenant_scoped_cache": True,
    "circuit_breaker": True,
}


class TenantConfigService:
    """
    SaaS Tenant Configuration Service.
    Resolves tenant-specific embedding model preferences, chunk budgets, and feature flags.
    """

    def __init__(self):
        self._tenant_configs: Dict[str, Dict[str, Any]] = {}

    # ── Real persistence ──

    async def load_tenant_config(self, tenant_id: str) -> Dict[str, Any]:
        """Reads a tenant's real settings from the DB into the in-memory cache. Call
        this once at the start of any workflow (e.g. an ingestion sync) before the
        synchronous get_* methods below are used, so they read real config instead of
        an always-empty cache."""
        from app.db.database import async_session_factory
        async with async_session_factory() as session:
            res = await session.execute(text("SELECT settings FROM tenants WHERE id = :tid"), {"tid": tenant_id})
            row = res.fetchone()
        config = (row[0] if row and row[0] else {}) or {}
        self._tenant_configs[tenant_id] = config
        return config

    async def set_tenant_config(self, tenant_id: str, config: Dict[str, Any]) -> None:
        """Persists a tenant's config to the DB and updates the in-memory cache
        immediately (merge, not replace — a partial update like {"feature_flags": {...}}
        doesn't wipe out an unrelated embedding_model override set earlier)."""
        from app.db.database import async_session_factory
        import json
        existing = self._tenant_configs.get(tenant_id) or await self.load_tenant_config(tenant_id)
        merged = {**existing, **config}
        async with async_session_factory() as session:
            await session.execute(
                text("UPDATE tenants SET settings = CAST(:settings AS jsonb), updated_at = now() WHERE id = :tid"),
                {"tid": tenant_id, "settings": json.dumps(merged)},
            )
            await session.commit()
        self._tenant_configs[tenant_id] = merged

    # ── Synchronous reads (unchanged signatures — safe for the Phase 1 hot path) ──

    def get_tenant_embedding_model(self, tenant_id: str) -> str:
        tenant_cfg = self._tenant_configs.get(tenant_id, {})
        return tenant_cfg.get("embedding_model", "BAAI/bge-large-en-v1.5")

    def get_tenant_chunk_policy(self, tenant_id: str, resource_category: str = "document") -> Dict[str, Any]:
        base_policy = get_chunking_policy(resource_category)
        tenant_cfg = self._tenant_configs.get(tenant_id, {})
        if "chunking_overrides" in tenant_cfg:
            base_policy = {**base_policy, **tenant_cfg["chunking_overrides"]}
        return base_policy

    def is_feature_enabled(self, tenant_id: str, feature_key: str) -> bool:
        tenant_cfg = self._tenant_configs.get(tenant_id, {})
        flags = tenant_cfg.get("feature_flags", {})
        return flags.get(feature_key, _DEFAULT_FEATURE_FLAGS.get(feature_key, False))


tenant_config_service = TenantConfigService()
