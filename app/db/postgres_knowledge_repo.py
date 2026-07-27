"""
PostgreSQL Knowledge Repository — Module 3
===========================================
Async PostgreSQL repository operating under Row-Level Security (RLS) for graph entities,
relationships, facts, conflicts, decisions, action recommendations, and workflows.
"""
import uuid
import json
from typing import List, Optional, Dict, Any
from sqlalchemy import text
from app.db.database import async_session_factory
from app.domain.graph_models import (
    EntityModel, RelationshipModel, FactModel, ConflictModel,
    DecisionModel, ActionRecommendationModel
)

class PostgresKnowledgeRepository:
    """Async PostgreSQL repository enforcing tenant isolation via RLS context and explicit tenant filtering."""

    async def create_entity(self, entity: EntityModel) -> str:
        """Insert a graph entity into AWS RDS PostgreSQL under RLS."""
        entity_id = entity.id or str(uuid.uuid4())
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL app.current_tenant_id = '{entity.tenant_id}'"))
                await session.execute(
                    text("""
                        INSERT INTO graph_entities (id, tenant_id, entity_type, canonical_name, state, confidence_score, trust_score, attributes, governance_tags)
                        VALUES (:id, :tenant_id, :entity_type, :canonical_name, :state, :confidence_score, :trust_score, :attributes, :governance_tags)
                    """),
                    {
                        "id": entity_id,
                        "tenant_id": entity.tenant_id,
                        "entity_type": entity.entity_type,
                        "canonical_name": entity.canonical_name,
                        "state": entity.state,
                        "confidence_score": entity.confidence_score,
                        "trust_score": entity.trust_score,
                        "attributes": json.dumps(entity.attributes),
                        "governance_tags": json.dumps(entity.governance_tags),
                    }
                )
                # Create primary alias
                await session.execute(
                    text("""
                        INSERT INTO graph_entity_aliases (id, tenant_id, entity_id, alias_name, match_type, confidence)
                        VALUES (:id, :tenant_id, :entity_id, :alias_name, 'exact', 1.0)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": entity.tenant_id,
                        "entity_id": entity_id,
                        "alias_name": entity.canonical_name,
                    }
                )
        return entity_id

    async def get_entity_by_canonical_name(self, tenant_id: str, canonical_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve entity by canonical name under tenant RLS and explicit tenant_id scoping."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
                res = await session.execute(
                    text("""
                        SELECT id, tenant_id, entity_type, canonical_name, state, confidence_score, trust_score, attributes 
                        FROM graph_entities 
                        WHERE tenant_id = :tenant_id AND canonical_name = :name AND is_current = TRUE
                    """),
                    {"tenant_id": tenant_id, "name": canonical_name}
                )
                row = res.fetchone()
                if not row:
                    return None
                return {
                    "id": str(row[0]),
                    "tenant_id": str(row[1]),
                    "entity_type": row[2],
                    "canonical_name": row[3],
                    "state": row[4],
                    "confidence_score": row[5],
                    "trust_score": row[6],
                    "attributes": row[7],
                }

    async def create_relationship(self, rel: RelationshipModel, document_id: Optional[str] = None, chunk_id: Optional[str] = None, snippet: str = "") -> str:
        """Insert graph relationship & source provenance into AWS RDS PostgreSQL."""
        rel_id = rel.id or str(uuid.uuid4())
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL app.current_tenant_id = '{rel.tenant_id}'"))
                await session.execute(
                    text("""
                        INSERT INTO graph_relationships (id, tenant_id, source_entity_id, target_entity_id, relation_type, causal_type, state, confidence_score, attributes)
                        VALUES (:id, :tenant_id, :source_id, :target_id, :relation_type, :causal_type, :state, :confidence_score, :attributes)
                    """),
                    {
                        "id": rel_id,
                        "tenant_id": rel.tenant_id,
                        "source_id": rel.source_entity_id,
                        "target_id": rel.target_entity_id,
                        "relation_type": rel.relation_type,
                        "causal_type": rel.causal_type,
                        "state": rel.state,
                        "confidence_score": rel.confidence_score,
                        "attributes": json.dumps(rel.attributes),
                    }
                )
                if snippet:
                    await session.execute(
                        text("""
                            INSERT INTO graph_relationship_sources (id, tenant_id, relationship_id, document_id, chunk_id, source_snippet)
                            VALUES (:id, :tenant_id, :rel_id, :doc_id, :chunk_id, :snippet)
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "tenant_id": rel.tenant_id,
                            "rel_id": rel_id,
                            "doc_id": document_id,
                            "chunk_id": chunk_id,
                            "snippet": snippet,
                        }
                    )
        return rel_id

    async def create_fact(self, fact: FactModel, document_id: Optional[str] = None, chunk_id: Optional[str] = None, snippet: str = "") -> str:
        """Insert structured fact into AWS RDS PostgreSQL."""
        fact_id = fact.id or str(uuid.uuid4())
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL app.current_tenant_id = '{fact.tenant_id}'"))
                await session.execute(
                    text("""
                        INSERT INTO graph_facts (id, tenant_id, fact_type, is_derived, metric_name, value, period, state, confidence_score, source_authority)
                        VALUES (:id, :tenant_id, :fact_type, :is_derived, :metric_name, :value, :period, :state, :confidence_score, :source_authority)
                    """),
                    {
                        "id": fact_id,
                        "tenant_id": fact.tenant_id,
                        "fact_type": fact.fact_type,
                        "is_derived": fact.is_derived,
                        "metric_name": fact.metric_name,
                        "value": fact.value,
                        "period": fact.period,
                        "state": fact.state,
                        "confidence_score": fact.confidence_score,
                        "source_authority": fact.source_authority,
                    }
                )
                if snippet:
                    await session.execute(
                        text("""
                            INSERT INTO graph_fact_sources (id, tenant_id, fact_id, document_id, chunk_id, source_snippet)
                            VALUES (:id, :tenant_id, :fact_id, :doc_id, :chunk_id, :snippet)
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "tenant_id": fact.tenant_id,
                            "fact_id": fact_id,
                            "doc_id": document_id,
                            "chunk_id": chunk_id,
                            "snippet": snippet,
                        }
                    )
        return fact_id

    async def save_conflict(self, conflict: ConflictModel) -> str:
        """Insert conflict record with dual evidence into AWS RDS PostgreSQL."""
        conflict_id = conflict.id or str(uuid.uuid4())
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL app.current_tenant_id = '{conflict.tenant_id}'"))
                await session.execute(
                    text("""
                        INSERT INTO graph_conflicts (id, tenant_id, conflict_type, entity_id, description, evidence_a_json, evidence_b_json, severity, resolution_status)
                        VALUES (:id, :tenant_id, :conflict_type, :entity_id, :description, :ev_a, :ev_b, :severity, :status)
                    """),
                    {
                        "id": conflict_id,
                        "tenant_id": conflict.tenant_id,
                        "conflict_type": conflict.conflict_type,
                        "entity_id": conflict.entity_id,
                        "description": conflict.description,
                        "ev_a": json.dumps(conflict.evidence_a_json),
                        "ev_b": json.dumps(conflict.evidence_b_json),
                        "severity": conflict.severity,
                        "status": conflict.resolution_status,
                    }
                )
        return conflict_id

    async def create_decision(self, decision: DecisionModel) -> str:
        """Insert decision intelligence record."""
        dec_id = decision.id or str(uuid.uuid4())
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL app.current_tenant_id = '{decision.tenant_id}'"))
                await session.execute(
                    text("""
                        INSERT INTO graph_decisions (id, tenant_id, decision_title, owner_id, rationale, expected_outcome, actual_outcome, state)
                        VALUES (:id, :tenant_id, :title, :owner_id, :rationale, :exp, :act, :state)
                    """),
                    {
                        "id": dec_id,
                        "tenant_id": decision.tenant_id,
                        "title": decision.decision_title,
                        "owner_id": decision.owner_id,
                        "rationale": decision.rationale,
                        "exp": decision.expected_outcome,
                        "act": decision.actual_outcome,
                        "state": decision.state,
                    }
                )
        return dec_id

    async def create_action_recommendation(self, rec: ActionRecommendationModel) -> str:
        """Insert action recommendation."""
        rec_id = rec.id or str(uuid.uuid4())
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL app.current_tenant_id = '{rec.tenant_id}'"))
                await session.execute(
                    text("""
                        INSERT INTO graph_action_recommendations (id, tenant_id, action_type, target_entity_id, recommendation_text, priority, status)
                        VALUES (:id, :tenant_id, :type, :target_id, :text, :priority, :status)
                    """),
                    {
                        "id": rec_id,
                        "tenant_id": rec.tenant_id,
                        "type": rec.action_type,
                        "target_id": rec.target_entity_id,
                        "text": rec.recommendation_text,
                        "priority": rec.priority,
                        "status": rec.status,
                    }
                )
        return rec_id

postgres_knowledge_repo = PostgresKnowledgeRepository()
