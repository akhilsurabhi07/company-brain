"""
Structured Enterprise Error Models — Module 4
============================================
Standardized JSON error contract for enterprise observability and failure handling.
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class RetrievalErrorDetails(BaseModel):
    stage: str
    tenant_id: str
    subsystem: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)

class RetrievalError(BaseModel):
    error_code: str
    message: str
    correlation_id: str
    retryable: bool = False
    details: Optional[RetrievalErrorDetails] = None
