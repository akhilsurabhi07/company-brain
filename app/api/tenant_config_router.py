"""
Tenant Configuration API
=========================
Lets a tenant's embedding model, chunk-policy overrides, and feature flags actually be
set and persisted — previously TenantConfigService had no setter at all, so it always
silently fell back to hardcoded defaults regardless of what anyone intended.
"""
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core_config.tenant_config_service import tenant_config_service

router = APIRouter(prefix="/api/v1/tenant-config", tags=["Tenant Configuration"])


class TenantConfigUpdateRequest(BaseModel):
    tenant_id: str
    embedding_model: Optional[str] = None
    chunking_overrides: Optional[Dict[str, Any]] = None
    feature_flags: Optional[Dict[str, bool]] = None


@router.get("")
async def get_tenant_config(tenant_id: str) -> Dict[str, Any]:
    """Returns the tenant's real persisted config (not hardcoded defaults)."""
    config = await tenant_config_service.load_tenant_config(tenant_id)
    return {"tenant_id": tenant_id, "config": config}


@router.post("")
async def update_tenant_config(req: TenantConfigUpdateRequest) -> Dict[str, Any]:
    """Persists a (partial) tenant config update — merged with, not replacing, whatever
    was set before."""
    update: Dict[str, Any] = {}
    if req.embedding_model is not None:
        update["embedding_model"] = req.embedding_model
    if req.chunking_overrides is not None:
        update["chunking_overrides"] = req.chunking_overrides
    if req.feature_flags is not None:
        update["feature_flags"] = req.feature_flags

    if not update:
        raise HTTPException(status_code=422, detail="Provide at least one of embedding_model, chunking_overrides, feature_flags.")

    await tenant_config_service.set_tenant_config(req.tenant_id, update)
    return {"status": "success", "tenant_id": req.tenant_id, "config": tenant_config_service._tenant_configs.get(req.tenant_id, {})}
