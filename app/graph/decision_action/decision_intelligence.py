"""
Decision Intelligence Engine — Module 3 (Domain 6)
===================================================
Tracks institutional decisions, owners, rationales, evidence, expected outcomes, and actual outcomes.
"""
from typing import Optional
from app.domain.graph_models import DecisionModel
from app.db.postgres_knowledge_repo import postgres_knowledge_repo

class DecisionIntelligenceEngine:
    """Manages institutional decision tracking."""

    async def record_decision(
        self,
        tenant_id: str,
        title: str,
        rationale: str,
        owner_id: Optional[str] = None,
        expected_outcome: Optional[str] = None
    ) -> str:
        """Records a new enterprise decision."""
        decision = DecisionModel(
            tenant_id=tenant_id,
            decision_title=title,
            owner_id=owner_id,
            rationale=rationale,
            expected_outcome=expected_outcome,
            state="Published"
        )
        return await postgres_knowledge_repo.create_decision(decision)

decision_intelligence_engine = DecisionIntelligenceEngine()
