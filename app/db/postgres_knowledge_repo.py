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
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(entity.tenant_id)})
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
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
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
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(rel.tenant_id)})
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
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(fact.tenant_id)})
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
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(conflict.tenant_id)})
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
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(decision.tenant_id)})
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
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(rec.tenant_id)})
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

    # ── Real read/aggregate queries (added 2026-08 to replace hardcoded fake
    # health/impact numbers in app/api/graph_api.py with genuine DB state) ──

    async def relationship_exists(self, tenant_id: str, source_entity_id: str, target_entity_id: str, relation_type: str) -> bool:
        """Idempotency check so re-ingestion doesn't accumulate duplicate edges."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("""
                    SELECT 1 FROM graph_relationships
                    WHERE tenant_id = :tid AND source_entity_id = :src AND target_entity_id = :tgt AND relation_type = :rel
                    LIMIT 1
                """),
                {"tid": tenant_id, "src": source_entity_id, "tgt": target_entity_id, "rel": relation_type},
            )
            return res.fetchone() is not None

    async def count_entities(self, tenant_id: str) -> int:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("SELECT COUNT(*) FROM graph_entities WHERE tenant_id = :tid AND is_current = TRUE"),
                {"tid": tenant_id},
            )
            return int(res.scalar() or 0)

    async def count_relationships(self, tenant_id: str) -> int:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("SELECT COUNT(*) FROM graph_relationships WHERE tenant_id = :tid AND is_current = TRUE"),
                {"tid": tenant_id},
            )
            return int(res.scalar() or 0)

    async def count_orphan_entities(self, tenant_id: str, entity_type: str) -> int:
        """Entities of a given type with zero relationships in either direction —
        a real (if simple) proxy for 'orphan projects', etc."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("""
                    SELECT COUNT(*) FROM graph_entities e
                    WHERE e.tenant_id = :tid AND e.entity_type = :etype AND e.is_current = TRUE
                      AND NOT EXISTS (
                          SELECT 1 FROM graph_relationships r
                          WHERE r.tenant_id = :tid AND (r.source_entity_id = e.id OR r.target_entity_id = e.id)
                      )
                """),
                {"tid": tenant_id, "etype": entity_type},
            )
            return int(res.scalar() or 0)

    async def count_active_conflicts(self, tenant_id: str) -> int:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("SELECT COUNT(*) FROM graph_conflicts WHERE tenant_id = :tid AND resolution_status != 'resolved'"),
                {"tid": tenant_id},
            )
            return int(res.scalar() or 0)

    # ── Real read queries backing the Decisions/Risks sidebar panels
    # (added 2026-08-22, Module 6B) — this data already existed and was
    # already populated via create_decision()/save_conflict() above; it was
    # simply never surfaced anywhere in the product before now. ──

    async def list_decisions(self, tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("""
                    SELECT id, decision_title, rationale, expected_outcome, actual_outcome, state, created_at
                    FROM graph_decisions WHERE tenant_id = :tid
                    ORDER BY created_at DESC LIMIT :lim
                """),
                {"tid": tenant_id, "lim": limit},
            )
            return [dict(row._mapping) for row in res.fetchall()]

    async def list_conflicts(self, tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("""
                    SELECT id, conflict_type, description, severity, resolution_status, created_at
                    FROM graph_conflicts WHERE tenant_id = :tid
                    ORDER BY
                        CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                        created_at DESC
                    LIMIT :lim
                """),
                {"tid": tenant_id, "lim": limit},
            )
            return [dict(row._mapping) for row in res.fetchall()]

    async def count_documents_without_relationships(self, tenant_id: str) -> int:
        """Documents that were ingested but have no extracted graph relationships tied
        to them yet — a real, honest proxy for 'knowledge gaps' (content sitting in the
        vault that hasn't been turned into structured knowledge)."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("""
                    SELECT COUNT(*) FROM documents d
                    WHERE d.tenant_id = :tid
                      AND NOT EXISTS (
                          SELECT 1 FROM graph_relationship_sources s WHERE s.tenant_id = :tid AND s.document_id = d.id
                      )
                """),
                {"tid": tenant_id},
            )
            return int(res.scalar() or 0)

    async def compute_documentation_coverage_pct(self, tenant_id: str) -> float:
        """Real % of ingested documents that actually have at least one chunk (i.e.
        genuinely made it through the embedding pipeline, not just landed in storage)."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            total = (await session.execute(text("SELECT COUNT(*) FROM documents WHERE tenant_id = :tid"), {"tid": tenant_id})).scalar() or 0
            if total == 0:
                return 0.0
            with_chunks = (await session.execute(
                text("SELECT COUNT(DISTINCT document_id) FROM document_chunks WHERE tenant_id = :tid"), {"tid": tenant_id}
            )).scalar() or 0
            return round(100.0 * with_chunks / total, 1)

    async def compute_knowledge_freshness_pct(self, tenant_id: str, within_days: int = 30) -> float:
        """Real % of documents ingested/updated within the freshness window."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            total = (await session.execute(text("SELECT COUNT(*) FROM documents WHERE tenant_id = :tid"), {"tid": tenant_id})).scalar() or 0
            if total == 0:
                return 0.0
            fresh = (await session.execute(
                text(f"SELECT COUNT(*) FROM documents WHERE tenant_id = :tid AND ingested_at >= now() - interval '{int(within_days)} days'"),
                {"tid": tenant_id},
            )).scalar() or 0
            return round(100.0 * fresh / total, 1)

    async def get_relationships_for_entity_name(self, tenant_id: str, entity_name: str, max_hops: int = 1) -> List[Dict[str, Any]]:
        """Real graph edges for a named entity — replaces the hardcoded sample_edges
        previously fed to the impact analyzer regardless of tenant_id.

        Real gap found via Module 4 inspection 2026-08-22: this (and the parallel,
        never-wired-in app/db/postgres_graph_repo.py — same underlying tables,
        duplicate access code) always did a single hop, no matter what depth a
        caller asked for; there was no recursive expansion anywhere in the
        codebase. "Multi-hop reasoning" was claimed by the Module 4 design but
        never actually implemented. max_hops now genuinely walks the graph via a
        bounded recursive CTE — default 1 keeps every existing caller's exact
        prior behavior unchanged. Bounded by max_hops (small, e.g. 2-3) and a
        final LIMIT, so a densely connected real graph can't blow up the result
        set or the query cost; tenant-scoped and is_current-filtered throughout,
        same as the 1-hop version.
        """
        if max_hops <= 1:
            async with async_session_factory() as session:
                await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
                res = await session.execute(
                    text("""
                        SELECT src.canonical_name, tgt.canonical_name, r.relation_type, 1 as hop
                        FROM graph_relationships r
                        JOIN graph_entities src ON src.id = r.source_entity_id
                        JOIN graph_entities tgt ON tgt.id = r.target_entity_id
                        WHERE r.tenant_id = :tid AND r.is_current = TRUE
                          AND (src.canonical_name = :name OR tgt.canonical_name = :name)
                    """),
                    {"tid": tenant_id, "name": entity_name},
                )
                return [{"source": row[0], "target": row[1], "relation": row[2], "hop": row[3]} for row in res.fetchall()]

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("""
                    WITH RECURSIVE graph_walk AS (
                        SELECT r.source_entity_id AS src_id, r.target_entity_id AS tgt_id,
                               src.canonical_name AS source, tgt.canonical_name AS target,
                               r.relation_type, 1 AS hop
                        FROM graph_relationships r
                        JOIN graph_entities src ON src.id = r.source_entity_id
                        JOIN graph_entities tgt ON tgt.id = r.target_entity_id
                        WHERE r.tenant_id = :tid AND r.is_current = TRUE
                          AND (src.canonical_name = :name OR tgt.canonical_name = :name)

                        UNION ALL

                        SELECT r.source_entity_id, r.target_entity_id,
                               src.canonical_name, tgt.canonical_name,
                               r.relation_type, gw.hop + 1
                        FROM graph_relationships r
                        JOIN graph_entities src ON src.id = r.source_entity_id
                        JOIN graph_entities tgt ON tgt.id = r.target_entity_id
                        JOIN graph_walk gw ON (
                            r.source_entity_id IN (gw.src_id, gw.tgt_id)
                            OR r.target_entity_id IN (gw.src_id, gw.tgt_id)
                        )
                        WHERE r.tenant_id = :tid AND r.is_current = TRUE AND gw.hop < :max_hops
                    )
                    SELECT DISTINCT source, target, relation_type, MIN(hop) AS hop
                    FROM graph_walk
                    GROUP BY source, target, relation_type
                    ORDER BY hop
                    LIMIT 100
                """),
                {"tid": tenant_id, "name": entity_name, "max_hops": max_hops},
            )
            return [{"source": row[0], "target": row[1], "relation": row[2], "hop": row[3]} for row in res.fetchall()]


postgres_knowledge_repo = PostgresKnowledgeRepository()
