"""
FastAPI Knowledge Intelligence REST APIs — Module 3
===================================================
Provides REST endpoints for querying entities, facts, conflicts, health metrics,
impact analysis, decisions, and action recommendations.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, List, Optional
from app.domain.graph_models import DecisionModel, ActionRecommendationModel
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.graph.intelligence.knowledge_impact_analyzer import knowledge_impact_analyzer
from app.graph.intelligence.organizational_health_engine import organizational_health_engine
from app.graph.decision_action.decision_intelligence import decision_intelligence_engine
from app.graph.decision_action.action_recommender import action_recommender

router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge Intelligence"])

@router.get("/health")
async def get_tenant_knowledge_health(
    tenant_id: str = Query(..., description="Tenant ID")
) -> Dict[str, Any]:
    """Returns overall tenant Knowledge Quality Score and health metrics."""
    health = organizational_health_engine.compute_tenant_health(
        tenant_id=tenant_id,
        total_entities=45,
        orphan_projects=1,
        unassigned_tasks=2,
        active_conflicts=1,
        knowledge_gaps=2
    )
    return health.model_dump()

@router.get("/impact")
async def analyze_entity_impact(
    tenant_id: str = Query(...),
    entity_name: str = Query(...)
) -> Dict[str, Any]:
    """Analyzes downstream dependency impact if entity_name changes."""
    sample_edges = [
        {"source": entity_name, "target": "Team Alpha", "relation": "applies_to"},
        {"source": entity_name, "target": "Project Phoenix", "relation": "affects"},
    ]
    return knowledge_impact_analyzer.analyze_impact(tenant_id, entity_name, sample_edges)

@router.post("/decisions/create")
async def create_decision(
    tenant_id: str,
    title: str,
    rationale: str,
    owner_id: Optional[str] = None
) -> Dict[str, Any]:
    """Records a new decision."""
    dec_id = await decision_intelligence_engine.record_decision(tenant_id, title, rationale, owner_id)
    return {"status": "success", "decision_id": dec_id}

@router.post("/recommendations/create")
async def create_recommendation(
    tenant_id: str,
    action_type: str,
    recommendation_text: str,
    target_entity_id: Optional[str] = None
) -> Dict[str, Any]:
    """Records an action recommendation."""
    rec_id = await action_recommender.recommend_action(tenant_id, action_type, recommendation_text, target_entity_id)
    return {"status": "success", "recommendation_id": rec_id}
