"""
Gateway Jobs & Webhooks Schemas — Module 5 EKAP
================================================
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class JobStatus(BaseModel):
    job_id: str
    tenant_id: str
    status: str  # PENDING, RUNNING, COMPLETED, FAILED
    query: str
    result: Optional[Dict[str, Any]] = None
    webhook_url: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None

class WebhookPayload(BaseModel):
    event: str = "job.completed"
    job_id: str
    tenant_id: str
    status: str
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str
