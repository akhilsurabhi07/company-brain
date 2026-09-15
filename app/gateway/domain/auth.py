"""
Gateway Auth Domain Models — Module 5 EKAP
===========================================
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class APIKeyMetadata(BaseModel):
    api_key_id: str
    tenant_id: str
    user_id: str
    roles: List[str] = Field(default_factory=lambda: ["Employee"])
    clearance_level: str = "Internal"
    tier: str = "Standard"
    is_active: bool = True

class UserIdentity(BaseModel):
    user_id: str
    tenant_id: str
    roles: List[str] = Field(default_factory=lambda: ["Employee"])
    clearance_level: str = "Internal"

class TenantSession(BaseModel):
    session_id: str
    tenant_id: str
    user_id: str
    identity: UserIdentity
