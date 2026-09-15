"""
Graph Domain Models — Module 4
=============================
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class GraphNode(BaseModel):
    id: str
    canonical_name: str
    entity_type: str
    confidence_score: float = 0.95

class GraphEdge(BaseModel):
    id: str
    source_id: str
    source_name: str
    relationship_type: str
    target_id: str
    target_name: str
    weight: float = 1.0

class GraphPath(BaseModel):
    path_id: str
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    description: str
