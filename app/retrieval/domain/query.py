"""
Query Domain Models — Module 4
=============================
Extensible Hierarchical & Multi-Dimensional Intent Model for Enterprise GraphRAG.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class IntentCandidate(BaseModel):
    intent_name: str
    confidence: float
    tier: str = "HIGH"  # HIGH (>= 0.85), MEDIUM (0.60 - 0.85), LOW (< 0.60)

class IntentConfidence(BaseModel):
    intent: float = 0.90
    entities: float = 0.95
    graph_match: float = 0.88
    rules_match: float = 0.92
    overall: float = 0.91

class QueryAnalysis(BaseModel):
    query: str
    primary_intent: str = "General"
    secondary_intents: List[str] = Field(default_factory=list)
    ranked_intents: List[IntentCandidate] = Field(default_factory=list)
    reasoning_type: str = "Lookup"  # Lookup, Aggregation, Comparison, Temporal, Causal, Dependency, Statistical
    entities: List[str] = Field(default_factory=list)
    department_scope: Optional[str] = None
    temporal_scope: Optional[Dict[str, Any]] = None
    output_constraints: List[str] = Field(default_factory=list)
    output_preference: str = "Detailed"
    is_ambiguous: bool = False
    confidence: IntentConfidence = Field(default_factory=IntentConfidence)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def intent(self) -> str:
        """Backward compatibility helper mapping `intent` to `primary_intent`."""
        return self.primary_intent

class RetrievalPlan(BaseModel):
    plan_id: str
    strategies: List[str] = Field(default_factory=lambda: ["dense", "bm25", "graph"])
    hop_depth: int = 2
    confidentiality_level: str = "Internal"
    resource_budget_ms: int = 500
    estimated_cost_units: int = 6  # Cost units: 1 (BM25 only), 3 (Dense+BM25), 6 (Dense+BM25+Graph), 8 (Full Cross-Encoder)
    retrieval_engine_version: str = "v1.0"
