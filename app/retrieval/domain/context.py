"""
Knowledge Context v1 Response Model — Module 4
===============================================
Canonical output API contract produced by Module 4.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.retrieval.domain.query import QueryAnalysis, RetrievalPlan
from app.retrieval.domain.evidence import Citation, EvidenceGroup, KnowledgeGap
from app.retrieval.domain.graph import GraphNode, GraphEdge, GraphPath

class ConfidenceBreakdown(BaseModel):
    overall: float = 0.95
    retrieval: float = 0.95
    graph: float = 0.95
    citation: float = 1.0
    reasoning: float = 0.90

class QualityMetrics(BaseModel):
    freshness_score: float = 0.95
    authority_score: float = 0.95
    completeness_score: float = 0.90
    consistency_score: float = 0.95
    trust_score: float = 0.95

class RetrievalExplanation(BaseModel):
    selected_strategy: List[str] = Field(default_factory=list)
    excluded_sources: List[str] = Field(default_factory=list)
    reason: str = "Standard Retrieval Policy Execution"

class KnowledgeContext(BaseModel):
    schema_version: str = "1.0"
    query: str
    intent: str
    execution_plan: Dict[str, Any] = Field(default_factory=dict)
    retrieved_chunks: List[Dict[str, Any]] = Field(default_factory=list)
    graph_entities: List[GraphNode] = Field(default_factory=list)
    graph_relationships: List[GraphEdge] = Field(default_factory=list)
    graph_paths: List[GraphPath] = Field(default_factory=list)
    derived_facts: List[Dict[str, Any]] = Field(default_factory=list)
    timelines: List[Dict[str, Any]] = Field(default_factory=list)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_groups: List[EvidenceGroup] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    confidence: ConfidenceBreakdown = Field(default_factory=ConfidenceBreakdown)
    quality: QualityMetrics = Field(default_factory=QualityMetrics)
    knowledge_gaps: List[KnowledgeGap] = Field(default_factory=list)
    retrieval_explanation: RetrievalExplanation = Field(default_factory=RetrievalExplanation)
    execution_trace: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
