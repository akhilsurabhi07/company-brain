"""
FastAPI Knowledge Intelligence REST APIs — Module 3
===================================================
Provides REST endpoints for querying entities, facts, conflicts, health metrics,
impact analysis, decisions, and action recommendations.
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Dict, Any, List, Optional
from sqlalchemy import text as _text
from app.domain.graph_models import DecisionModel, ActionRecommendationModel
from app.db.database import async_session_factory
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.db.postgres_graph_repo import postgres_graph_repo
from app.graph.intelligence.knowledge_impact_analyzer import knowledge_impact_analyzer
from app.graph.intelligence.organizational_health_engine import organizational_health_engine
from app.graph.decision_action.decision_intelligence import decision_intelligence_engine
from app.graph.decision_action.action_recommender import action_recommender
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token
from app.security.content_redaction import redact_if_restricted

router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge Intelligence"])

@router.get("/health")
async def get_tenant_knowledge_health(
    tenant_id: str = Query(..., description="Tenant ID"),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Returns overall tenant Knowledge Quality Score and health metrics, computed from
    the tenant's real graph/document state — not fixed sample numbers. Real entity/
    relationship extraction now runs for GitHub, Jira, Slack, Google Drive, SharePoint,
    and WhatsApp (this comment was stale — updated 2026-08-21 after verifying the actual
    code, not just an old docstring); Teams is still a stub connector, so it alone
    contributes no real graph data. These numbers will honestly be low or zero for a
    tenant that hasn't ingested anything through a real connector sync yet — a document
    inserted directly (bypassing ingestion, e.g. a seed script) never runs extract_graph()
    at all, which is real state, not a placeholder."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    total_entities = await postgres_knowledge_repo.count_entities(tenant_id)
    orphan_projects = await postgres_knowledge_repo.count_orphan_entities(tenant_id, "project")
    unassigned_tasks = await postgres_knowledge_repo.count_orphan_entities(tenant_id, "task")
    active_conflicts = await postgres_knowledge_repo.count_active_conflicts(tenant_id)
    knowledge_gaps = await postgres_knowledge_repo.count_documents_without_relationships(tenant_id)

    health = organizational_health_engine.compute_tenant_health(
        tenant_id=tenant_id,
        total_entities=total_entities,
        orphan_projects=orphan_projects,
        unassigned_tasks=unassigned_tasks,
        active_conflicts=active_conflicts,
        knowledge_gaps=knowledge_gaps,
    )
    result = health.model_dump()
    # compute_tenant_health still hardcodes these two internally (out of scope for this
    # fix — see its own docstring) — override with real computed values here.
    result["knowledge_freshness_pct"] = await postgres_knowledge_repo.compute_knowledge_freshness_pct(tenant_id)
    result["documentation_coverage_pct"] = await postgres_knowledge_repo.compute_documentation_coverage_pct(tenant_id)
    return result

@router.get("/impact")
async def analyze_entity_impact(
    tenant_id: str = Query(...),
    entity_name: str = Query(...),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Analyzes downstream dependency impact if entity_name changes, using real graph
    edges for this tenant — an entity with no real relationships yet honestly returns
    zero impact rather than a fabricated Team Alpha/Project Phoenix example."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    real_edges = await postgres_knowledge_repo.get_relationships_for_entity_name(tenant_id, entity_name)
    return knowledge_impact_analyzer.analyze_impact(tenant_id, entity_name, real_edges)

@router.get("/graph-context")
async def get_graph_context_for_query(
    tenant_id: str = Query(...),
    query: str = Query(..., description="Free-text user query/message to find real graph context for"),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real replacement for the UI's 'Knowledge Graph' panel, which used to draw the
    exact same two hardcoded fake nodes ('Enterprise Knowledge', 'Knowledge Context')
    regardless of what was actually asked. Finds a real entity from this tenant's
    graph_entities whose name appears in the query, and returns its real neighbors
    (postgres_graph_repo.get_neighbors — frozen, unmodified, just consumed). Honestly
    reports no match rather than fabricating a graph when nothing real applies."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    q_lower = query.strip().lower()
    if not q_lower:
        return {"matched": False, "nodes": [], "edges": [], "message": "Empty query."}

    async with async_session_factory() as session:
        await session.execute(_text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        res = await session.execute(
            _text("""
                SELECT id, canonical_name, entity_type FROM graph_entities
                WHERE tenant_id = :tid AND POSITION(LOWER(canonical_name) IN :q) > 0
                ORDER BY LENGTH(canonical_name) DESC
                LIMIT 1
            """),
            {"tid": tenant_id, "q": q_lower},
        )
        row = res.fetchone()

    if not row:
        return {
            "matched": False, "nodes": [], "edges": [],
            "message": "No entity from your knowledge graph matches this query yet.",
        }

    entity_id, entity_name, entity_type = str(row.id), row.canonical_name, row.entity_type
    neighbors = await postgres_graph_repo.get_neighbors(tenant_id, entity_id, max_hops=1)

    nodes_by_id: Dict[str, Dict[str, Any]] = {
        entity_id: {"id": entity_id, "label": entity_name, "type": entity_type}
    }
    edges = []
    for n in neighbors:
        nodes_by_id.setdefault(n["source_id"], {"id": n["source_id"], "label": n["source_name"], "type": n["source_type"]})
        nodes_by_id.setdefault(n["target_id"], {"id": n["target_id"], "label": n["target_name"], "type": n["target_type"]})
        edges.append({"from": n["source_id"], "to": n["target_id"], "label": n["relationship_type"]})

    return {
        "matched": True,
        "matched_entity": entity_name,
        "nodes": list(nodes_by_id.values()),
        "edges": edges,
    }

@router.get("/architecture-graph")
async def get_architecture_graph_overview(
    tenant_id: str = Query(...),
    limit: int = Query(25, ge=1, le=100, description="Max entities to include in the overview"),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real Module 6B 'Architecture Graph' panel (2026-08-23) — a standalone,
    query-free browse view of this tenant's real knowledge graph, unlike
    /graph-context above which requires a query to find a single matching
    entity. Reuses the exact same real graph_entities/graph_relationships
    tables and node/edge shape as /graph-context so the frontend's existing
    renderBasicGraph() canvas renderer works unmodified. Shows the tenant's
    most-connected entities first (real relationship count), not an
    arbitrary or fabricated ordering."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)

    async with async_session_factory() as session:
        await session.execute(_text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        entities_res = await session.execute(
            _text("""
                SELECT e.id, e.canonical_name, e.entity_type,
                       (SELECT COUNT(*) FROM graph_relationships r
                        WHERE r.tenant_id = e.tenant_id AND (r.source_entity_id = e.id OR r.target_entity_id = e.id)) AS degree
                FROM graph_entities e
                WHERE e.tenant_id = :tid AND e.is_current = TRUE
                ORDER BY degree DESC, e.canonical_name ASC
                LIMIT :lim
            """),
            {"tid": tenant_id, "lim": limit},
        )
        entity_rows = entities_res.fetchall()
        if not entity_rows:
            return {"matched": False, "nodes": [], "edges": [], "message": "No entities in your knowledge graph yet."}

        entity_ids = [str(r.id) for r in entity_rows]
        nodes_by_id: Dict[str, Dict[str, Any]] = {
            str(r.id): {"id": str(r.id), "label": r.canonical_name, "type": r.entity_type} for r in entity_rows
        }

        rel_res = await session.execute(
            _text("""
                SELECT r.source_entity_id, r.target_entity_id, r.relation_type,
                       s.canonical_name AS source_name, s.entity_type AS source_type,
                       t.canonical_name AS target_name, t.entity_type AS target_type
                FROM graph_relationships r
                JOIN graph_entities s ON s.id = r.source_entity_id
                JOIN graph_entities t ON t.id = r.target_entity_id
                WHERE r.tenant_id = :tid
                  AND r.source_entity_id = ANY(:ids) AND r.target_entity_id = ANY(:ids)
            """),
            {"tid": tenant_id, "ids": entity_ids},
        )
        edges = []
        for r in rel_res.fetchall():
            src_id, tgt_id = str(r.source_entity_id), str(r.target_entity_id)
            nodes_by_id.setdefault(src_id, {"id": src_id, "label": r.source_name, "type": r.source_type})
            nodes_by_id.setdefault(tgt_id, {"id": tgt_id, "label": r.target_name, "type": r.target_type})
            edges.append({"from": src_id, "to": tgt_id, "label": r.relation_type})

    return {
        "matched": True,
        "matched_entity": None,
        "nodes": list(nodes_by_id.values()),
        "edges": edges,
    }


@router.get("/decisions")
async def list_decisions(
    tenant_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real Module 6B 'Decisions' sidebar panel data (2026-08-22) — this data
    already existed (graph_decisions, populated via create_decision() below)
    but was never surfaced anywhere in the product before now. Applies the
    same sentence-level RBAC redaction used for decisions surfaced through
    chat — a non-admin caller must never see a restricted figure (salary/
    payroll/compensation/bonus) here either, just because this is a
    different endpoint from /chat/turn."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    caller_role = (token.get("role") or "member").lower()
    rows = await postgres_knowledge_repo.list_decisions(tenant_id, limit=limit)

    decisions = []
    for r in rows:
        # A decision whose rationale is entirely restricted still keeps its
        # title/state visible with a placeholder rationale, rather than
        # disappearing from the list outright — a member should be able to
        # see "a decision was made here" without seeing the restricted
        # figures, same as how the chat path never claims a topic doesn't
        # exist just because its detail is redacted.
        rationale = redact_if_restricted(r.get("rationale") or "", caller_role)
        if rationale is None:
            rationale = "[Content withheld — restricted to admins.]"
        decisions.append({
            "id": str(r["id"]),
            "title": r["decision_title"],
            "rationale": rationale,
            "expected_outcome": r.get("expected_outcome"),
            "actual_outcome": r.get("actual_outcome"),
            "state": r.get("state"),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })
    return {"decisions": decisions, "count": len(decisions)}


@router.get("/risks")
async def list_risks(
    tenant_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real Module 6B 'Risks' sidebar panel (2026-08-22). The vision's 'Risks'
    concept doesn't have its own table — the closest real, already-populated
    data is graph_conflicts (data sources disagreeing with each other, e.g.
    two documents giving different probation periods), which is a genuine
    proxy for 'something here needs a human to look at it', surfaced
    honestly as such rather than inventing a separate risk-scoring system."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    caller_role = (token.get("role") or "member").lower()
    rows = await postgres_knowledge_repo.list_conflicts(tenant_id, limit=limit)

    risks = []
    for r in rows:
        description = redact_if_restricted(r.get("description") or "", caller_role)
        if description is None:
            description = "[Content withheld — restricted to admins.]"
        risks.append({
            "id": str(r["id"]),
            "type": r.get("conflict_type"),
            "description": description,
            "severity": r.get("severity"),
            "resolution_status": r.get("resolution_status"),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })
    return {"risks": risks, "count": len(risks)}


@router.post("/decisions/create")
async def create_decision(
    tenant_id: str,
    title: str,
    rationale: str,
    owner_id: Optional[str] = None,
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Records a new decision."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    dec_id = await decision_intelligence_engine.record_decision(tenant_id, title, rationale, owner_id)
    return {"status": "success", "decision_id": dec_id}

@router.post("/recommendations/create")
async def create_recommendation(
    tenant_id: str,
    action_type: str,
    recommendation_text: str,
    target_entity_id: Optional[str] = None,
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Records an action recommendation."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    rec_id = await action_recommender.recommend_action(tenant_id, action_type, recommendation_text, target_entity_id)
    return {"status": "success", "recommendation_id": rec_id}
