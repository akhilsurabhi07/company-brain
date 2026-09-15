"""
Retrieval Domain Models — Module 4
=================================
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class Candidate(BaseModel):
    id: str
    item_type: str  # "dense_chunk", "bm25_chunk", "graph_fact", "graph_entity", "graph_relationship"
    content: str
    score: float = 0.0
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)

class RetrievalPipelineContext(BaseModel):
    correlation_id: str
    tenant_id: str
    user_id: Optional[str] = None
    query: str
    analysis: Optional[Dict[str, Any]] = None
    plan: Optional[Dict[str, Any]] = None
    timing_ms: Dict[str, float] = Field(default_factory=dict)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    feature_flags: Dict[str, bool] = Field(default_factory=dict)
