"""
Evidence Domain Models — Module 4
================================
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class Citation(BaseModel):
    citation_id: str
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    title: str
    page_number: Optional[int] = None
    section_id: Optional[str] = None
    source_app: str = "gdrive"
    snippet: str

class Evidence(BaseModel):
    id: str
    content: str
    evidence_type: str  # "chunk", "fact", "relationship", "derived_risk"
    relevance_score: float
    citation: Optional[Citation] = None

class EvidenceGroup(BaseModel):
    group_id: str
    group_name: str
    items: List[Evidence] = Field(default_factory=list)
    group_score: float = 0.0

class KnowledgeGap(BaseModel):
    gap_type: str  # "MissingOwner", "MissingApproval", "UnlinkedDependency"
    target_node: str
    impact: str = "High"
    description: str
