"""
Gateway Audit & Jobs Domain Models — Module 5 EKAP
===================================================
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class AuditRecord(BaseModel):
    audit_id: str
    tenant_id: str
    user_id: str
    role: str
    endpoint: str
    query: str
    result_count: int
    confidence_score: float
    cost_units: int
    latency_ms: float
    timestamp: str

class JobStatus(BaseModel):
    job_id: str
    tenant_id: str
    status: str  # PENDING, RUNNING, COMPLETED, FAILED
    query: str
    result: Optional[Dict[str, Any]] = None
    webhook_url: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
