"""
Graph Models & Pydantic Schemas — Module 3
=========================================
Pydantic v2 data models for the Enterprise Knowledge Intelligence Platform.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class EntityModel(BaseModel):
    id: Optional[str] = None
    tenant_id: str
    entity_type: str
    canonical_name: str
    state: str = "Candidate"
    confidence_score: float = 1.0
    trust_score: float = 1.0
    attributes: Dict[str, Any] = Field(default_factory=dict)
    governance_tags: List[str] = Field(default_factory=list)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    is_current: bool = True
    created_at: Optional[datetime] = None

class EntityAliasModel(BaseModel):
    id: Optional[str] = None
    tenant_id: str
    entity_id: str
    alias_name: str
    match_type: str = "exact"
    confidence: float = 1.0

class RelationshipModel(BaseModel):
    id: Optional[str] = None
    tenant_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    causal_type: str = "structural"
    state: str = "Candidate"
    confidence_score: float = 1.0
    attributes: Dict[str, Any] = Field(default_factory=dict)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    is_current: bool = True
    created_at: Optional[datetime] = None

class FactModel(BaseModel):
    id: Optional[str] = None
    tenant_id: str
    fact_type: str
    is_derived: bool = False
    metric_name: str
    value: str
    period: Optional[str] = None
    state: str = "Candidate"
    confidence_score: float = 1.0
    source_authority: float = 1.0
    temporal_timestamp: Optional[datetime] = None
    is_current: bool = True
    created_at: Optional[datetime] = None

class ConflictModel(BaseModel):
    id: Optional[str] = None
    tenant_id: str
    conflict_type: str
    entity_id: Optional[str] = None
    description: str
    evidence_a_json: Dict[str, Any] = Field(default_factory=dict)
    evidence_b_json: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "medium"
    resolution_status: str = "active"
    created_at: Optional[datetime] = None

class DecisionModel(BaseModel):
    id: Optional[str] = None
    tenant_id: str
    decision_title: str
    owner_id: Optional[str] = None
    rationale: str
    expected_outcome: Optional[str] = None
    actual_outcome: Optional[str] = None
    state: str = "Published"
    created_at: Optional[datetime] = None

class ActionRecommendationModel(BaseModel):
    id: Optional[str] = None
    tenant_id: str
    action_type: str
    target_entity_id: Optional[str] = None
    recommendation_text: str
    priority: str = "medium"
    status: str = "open"
    created_at: Optional[datetime] = None

class KnowledgeQualityHealthModel(BaseModel):
    tenant_id: str
    quality_score: float  # 0 to 100
    knowledge_freshness_pct: float
    documentation_coverage_pct: float
    orphan_projects_count: int
    unassigned_tasks_count: int
    active_conflicts_count: int
    knowledge_gaps_count: int
