"""Formalized ConversationPlan Domain Object for Module 6A."""

import uuid
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class PlanningStrategy(str, Enum):
    DIRECT_ANSWER = "DIRECT_ANSWER"
    EXECUTIVE_SUMMARY = "EXECUTIVE_SUMMARY"
    TECHNICAL_DEEP_DIVE = "TECHNICAL_DEEP_DIVE"
    ROOT_CAUSE_ANALYSIS = "ROOT_CAUSE_ANALYSIS"
    TEACHING_EXPLANATION = "TEACHING_EXPLANATION"
    COMPLIANCE_AUDIT = "COMPLIANCE_AUDIT"
    COMPARATIVE_RESEARCH = "COMPARATIVE_RESEARCH"


class ConversationPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:12]}")
    query_intent: str
    strategy: PlanningStrategy
    persona: str
    conversation_mode: str
    reasoning_depth: str = "STANDARD"  # LIGHT, STANDARD, DEEP
    temperature: float = 0.7
    response_format: str = "MARKDOWN"  # MARKDOWN, JSON, STRUCTURED
    provider_preference: Optional[str] = None
    requires_consensus: bool = False
    requires_streaming: bool = True
    requires_explanation: bool = False
    requires_review: bool = True
    confidence: float = 1.0
    max_token_budget: int = 4096
    recommended_personas: List[str] = Field(default_factory=list)
    # Module 6A Subsystem 1 Extensions
    retrieval_needed: bool = True
    sources_to_query: List[str] = Field(default_factory=lambda: ["vector", "keyword", "graph"])
    is_follow_up: bool = False
    narrowed_query: Optional[str] = None

