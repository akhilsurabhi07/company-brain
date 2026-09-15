"""
Gateway Auth & Response Domain Schemas — Module 5 EKAP
======================================================
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.retrieval.domain.context import KnowledgeContext

class UserIdentity(BaseModel):
    user_id: str
    tenant_id: str
    roles: List[str] = Field(default_factory=lambda: ["Employee"])
    clearance_level: str = "Internal"  # Internal, Confidential, Restricted

class TenantSession(BaseModel):
    session_id: str
    tenant_id: str
    user_id: str
    identity: UserIdentity

class APIResponse(BaseModel):
    success: bool = True
    correlation_id: str
    tenant_id: str
    api_version: str = "v1"
    format: str = "json"
    data: Dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: float = 0.0
