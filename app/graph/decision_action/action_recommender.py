"""
Action Recommendation Engine — Module 3 (Domain 6)
===================================================
Generates actionable maintenance recommendations (e.g., assign owner to orphan project, review contract).
"""
from typing import Optional
from app.domain.graph_models import ActionRecommendationModel
from app.db.postgres_knowledge_repo import postgres_knowledge_repo

class ActionRecommender:
    """Generates actionable maintenance recommendations."""

    async def recommend_action(
        self,
        tenant_id: str,
        action_type: str,
        recommendation_text: str,
        target_entity_id: Optional[str] = None,
        priority: str = "medium"
    ) -> str:
        """Saves a maintenance recommendation."""
        rec = ActionRecommendationModel(
            tenant_id=tenant_id,
            action_type=action_type,
            target_entity_id=target_entity_id,
            recommendation_text=recommendation_text,
            priority=priority,
            status="open"
        )
        return await postgres_knowledge_repo.create_action_recommendation(rec)

action_recommender = ActionRecommender()
