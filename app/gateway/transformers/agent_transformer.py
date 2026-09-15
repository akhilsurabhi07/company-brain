"""
AI Agent, Dashboard & Mobile Response Transformers — Module 5 EKAP
===================================================================
"""
from typing import Dict, Any
from app.retrieval.domain.context import KnowledgeContext

class AgentTransformer:
    """Formats KnowledgeContext into structured JSON for Autonomous AI Agents."""

    def transform(self, context: KnowledgeContext) -> Dict[str, Any]:
        return {
            "schema_version": context.schema_version,
            "query": context.query,
            "intent": context.intent,
            "facts": [f.get("content") for f in context.derived_facts],
            "evidence": [c.get("content") for c in context.retrieved_chunks[:5]],
            "confidence_score": context.confidence.overall,
            "citations": [c.citation_id for c in context.citations]
        }

class DashboardTransformer:
    """Formats KnowledgeContext into JSON with metrics for Executive Dashboards."""

    def transform(self, context: KnowledgeContext) -> Dict[str, Any]:
        return {
            "query": context.query,
            "intent": context.intent,
            "quality_metrics": context.quality.model_dump(),
            "confidence_breakdown": context.confidence.model_dump(),
            "evidence_count": len(context.retrieved_chunks),
            "citations_count": len(context.citations),
            "knowledge_gaps": [g.model_dump() for g in context.knowledge_gaps]
        }

class MobileTransformer:
    """Formats KnowledgeContext into ultra-compact JSON for Mobile Clients."""

    def transform(self, context: KnowledgeContext) -> Dict[str, Any]:
        return {
            "q": context.query,
            "intent": context.intent,
            "top_fact": context.derived_facts[0].get("content") if context.derived_facts else None,
            "confidence": context.confidence.overall,
            "citations_count": len(context.citations)
        }

agent_transformer = AgentTransformer()
dashboard_transformer = DashboardTransformer()
mobile_transformer = MobileTransformer()
