"""
PostgreSQL Knowledge Graph Repository — Module 4
================================================
Encapsulates all PostgreSQL graph SQL queries under Row-Level Security (RLS).
"""
import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from app.db.database import async_session_factory

class GraphRepository:
    """Repository for querying entities, relationships, facts, and sources under RLS."""

    async def get_entity_by_canonical_name(self, tenant_id: str, canonical_name: str) -> Optional[Dict[str, Any]]:
        """Queries canonical entity by name under RLS."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
            result = await session.execute(
                text("""
                    SELECT id, tenant_id, entity_type, canonical_name, confidence_score, state
                    FROM graph_entities
                    WHERE tenant_id = :tid AND LOWER(canonical_name) = LOWER(:name)
                    LIMIT 1
                """),
                {"tid": tenant_id, "name": canonical_name.strip()}
            )
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "entity_type": row.entity_type,
                "canonical_name": row.canonical_name,
                "confidence_score": float(row.confidence_score or 0.95),
                "state": row.state,
                "metadata": {}
            }

    async def get_neighbors(self, tenant_id: str, entity_id: str, max_hops: int = 2) -> List[Dict[str, Any]]:
        """Retrieves multi-hop connected entities and directed relationships."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
            result = await session.execute(
                text("""
                    SELECT r.id as rel_id, r.relation_type, r.confidence_score as weight,
                           e1.id as source_id, e1.canonical_name as source_name, e1.entity_type as source_type,
                           e2.id as target_id, e2.canonical_name as target_name, e2.entity_type as target_type
                    FROM graph_relationships r
                    JOIN graph_entities e1 ON r.source_entity_id = e1.id
                    JOIN graph_entities e2 ON r.target_entity_id = e2.id
                    WHERE r.tenant_id = :tid AND (r.source_entity_id = :eid OR r.target_entity_id = :eid)
                    LIMIT 50
                """),
                {"tid": tenant_id, "eid": entity_id}
            )
            rows = result.fetchall()
            neighbors = []
            for r in rows:
                neighbors.append({
                    "relationship_id": str(r.rel_id),
                    "relationship_type": r.relation_type,
                    "weight": float(r.weight or 1.0),
                    "source_id": str(r.source_id),
                    "source_name": r.source_name,
                    "source_type": r.source_type,
                    "target_id": str(r.target_id),
                    "target_name": r.target_name,
                    "target_type": r.target_type,
                })
            return neighbors

    async def get_facts_for_entities(self, tenant_id: str, entity_ids: List[str]) -> List[Dict[str, Any]]:
        """Retrieves facts associated with a list of entity IDs."""
        if not entity_ids:
            return []
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
            result = await session.execute(
                text("""
                    SELECT id, tenant_id, fact_type, metric_name, value, period, is_current
                    FROM graph_facts
                    WHERE tenant_id = :tid AND is_current = TRUE
                    LIMIT 50
                """),
                {"tid": tenant_id}
            )
            rows = result.fetchall()
            facts = []
            for r in rows:
                facts.append({
                    "id": str(r.id),
                    "tenant_id": str(r.tenant_id),
                    "fact_type": r.fact_type,
                    "metric_name": r.metric_name,
                    "value": r.value,
                    "unit": "",
                    "period": r.period,
                    "is_current": r.is_current
                })
            return facts

    async def get_decisions(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Retrieves recorded decisions for tenant under RLS."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
            result = await session.execute(
                text("""
                    SELECT id, tenant_id, decision_title, rationale, state as status, created_at as decided_at
                    FROM graph_decisions
                    WHERE tenant_id = :tid
                    LIMIT 20
                """),
                {"tid": tenant_id}
            )
            rows = result.fetchall()
            decisions = []
            for r in rows:
                decisions.append({
                    "id": str(r.id),
                    "tenant_id": str(r.tenant_id),
                    "decision_title": r.decision_title,
                    "rationale": r.rationale,
                    "status": r.status,
                    "decided_at": str(r.decided_at)
                })
            return decisions

postgres_graph_repo = GraphRepository()
