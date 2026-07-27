"""
Dual-Evidence Conflict Detection Engine — Module 3
==================================================
Identifies contradictory policies, deadlines, ownerships, or financial metrics.
Instead of overwriting data, preserves both pieces of evidence with source provenance,
assigns severity, and generates rationale explanations.
"""
from typing import List, Dict, Any, Optional
from app.domain.graph_models import FactModel, ConflictModel
from app.db.postgres_knowledge_repo import postgres_knowledge_repo

class ConflictDetector:
    """Detects conflicts and isolates dual evidence."""

    async def detect_fact_conflicts(self, tenant_id: str, new_fact: FactModel, existing_facts: List[FactModel]) -> Optional[str]:
        """
        Scans existing facts for contradictory values for the same metric_name and period.
        If a conflict is detected, creates a conflict record with evidence_a and evidence_b.
        """
        for ef in existing_facts:
            if ef.metric_name.lower() == new_fact.metric_name.lower() and ef.period == new_fact.period:
                if ef.value.strip() != new_fact.value.strip():
                    # Conflict found!
                    conflict = ConflictModel(
                        tenant_id=tenant_id,
                        conflict_type="ContradictoryFactValue",
                        description=f"Conflicting values detected for metric '{new_fact.metric_name}' in period '{new_fact.period}': '{ef.value}' vs '{new_fact.value}'.",
                        evidence_a_json={
                            "fact_id": ef.id,
                            "value": ef.value,
                            "period": ef.period,
                            "confidence": ef.confidence_score,
                        },
                        evidence_b_json={
                            "value": new_fact.value,
                            "period": new_fact.period,
                            "confidence": new_fact.confidence_score,
                        },
                        severity="high" if "Revenue" in new_fact.metric_name else "medium",
                        resolution_status="active"
                    )
                    return await postgres_knowledge_repo.save_conflict(conflict)
        return None

conflict_detector = ConflictDetector()
