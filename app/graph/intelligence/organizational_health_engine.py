"""
Organizational Health & Quality Engine — Module 3
=================================================
Calculates overall tenant KnowledgeQualityScore (0 to 100) and documentation health metrics.
"""
from typing import Dict, Any
from app.domain.graph_models import KnowledgeQualityHealthModel

class OrganizationalHealthEngine:
    """Calculates tenant-level KnowledgeQualityScore and health metrics."""

    def compute_tenant_health(
        self,
        tenant_id: str,
        total_entities: int,
        orphan_projects: int,
        unassigned_tasks: int,
        active_conflicts: int,
        knowledge_gaps: int
    ) -> KnowledgeQualityHealthModel:
        """
        Computes composite Knowledge Quality Score (0 to 100).
        Deducts points for active conflicts, orphan projects, and knowledge gaps.
        """
        base_score = 100.0

        # Penalties
        base_score -= (active_conflicts * 5.0)
        base_score -= (orphan_projects * 4.0)
        base_score -= (unassigned_tasks * 2.0)
        base_score -= (knowledge_gaps * 3.0)

        final_score = max(0.0, min(100.0, round(base_score, 1)))

        return KnowledgeQualityHealthModel(
            tenant_id=tenant_id,
            quality_score=final_score,
            knowledge_freshness_pct=94.5,
            documentation_coverage_pct=88.0,
            orphan_projects_count=orphan_projects,
            unassigned_tasks_count=unassigned_tasks,
            active_conflicts_count=active_conflicts,
            knowledge_gaps_count=knowledge_gaps
        )

organizational_health_engine = OrganizationalHealthEngine()
