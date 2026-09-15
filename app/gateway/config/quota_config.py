"""
Feature & Quota Configs — Module 5 EKAP
=======================================
"""
from typing import Dict, Any
from pydantic import BaseModel, Field

class QuotaPolicyConfig(BaseModel):
    requests_per_minute: int = 120
    monthly_query_quota: int = 100000
    allowed_confidentiality_levels: list = Field(default_factory=lambda: ["Internal", "Confidential", "Restricted"])

class TenantQuotaConfigs(BaseModel):
    tiers: Dict[str, QuotaPolicyConfig] = Field(default_factory=lambda: {
        "Internal": QuotaPolicyConfig(requests_per_minute=1000, monthly_query_quota=1000000),
        "Standard": QuotaPolicyConfig(requests_per_minute=120, monthly_query_quota=50000),
        "Enterprise": QuotaPolicyConfig(requests_per_minute=600, monthly_query_quota=500000)
    })

tenant_quota_configs = TenantQuotaConfigs()
