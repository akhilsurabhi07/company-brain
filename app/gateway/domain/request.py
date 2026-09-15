"""
Gateway Request Domain Schemas — Module 5 EKAP
=============================================
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="User search query string")
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = "Employee"
    format: str = Field(default="json", description="json, markdown, agent_schema, mobile")
    max_results: int = Field(default=10, ge=1, le=100)

class ContextQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = "Employee"
    format: str = Field(default="json")

class JobRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    tenant_id: Optional[str] = None
    webhook_url: Optional[str] = None
    format: str = Field(default="json")
