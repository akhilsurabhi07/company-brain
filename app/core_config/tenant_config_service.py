"""
Tenant Feature Flags & Configuration Service
============================================
Provides tenant-scoped feature flags and dynamic configuration settings.
"""
from typing import Dict, Any
from app.core_config.chunking_config import get_chunking_policy
from app.core_config.model_capability_registry import get_model_capability, ModelCapability

class TenantConfigService:
    """
    SaaS Tenant Configuration Service.
    Resolves tenant-specific embedding model preferences, chunk budgets, and feature flags.
    """

    def __init__(self):
        self._tenant_configs: Dict[str, Dict[str, Any]] = {}

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
        default_flags = {
            "parent_child_rag": True,
            "rrf_hybrid_search": True,
            "tenant_scoped_cache": True,
            "circuit_breaker": True,
        }
        return flags.get(feature_key, default_flags.get(feature_key, False))

tenant_config_service = TenantConfigService()
