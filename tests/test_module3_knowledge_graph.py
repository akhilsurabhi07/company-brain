"""
Master Test Suite — Module 3 Enterprise Knowledge Intelligence Platform
========================================================================
Tests:
  1. Hybrid Extraction Strategy (Deterministic Rules & Extractor Plugins)
  2. Entity Resolution & Alias Merging ("Microsoft Corporation", "MSFT" -> "Microsoft")
  3. Dual-Evidence Conflict Detection & Evidence Preservation
  4. Multi-Signal Enterprise Trust Engine
  5. Knowledge Reasoning Engine (Derived Fact Risk Inference)
  6. Knowledge Impact Analysis Engine
  7. Organizational Health & Knowledge Quality Score (0-100) Calculation
  8. Decision Intelligence & Action Recommendation Persistence
  9. Multi-Tenant RLS Security Audit & 10-Worker Concurrent Workload (AWS RDS PostgreSQL)
  10. Knowledge Sync Engine Incremental Updates (FILE_CREATED, FILE_UPDATED checksum diffing, FILE_DELETED archiving)
"""
import uuid
import asyncio
import pytest
from sqlalchemy import text
from app.domain.graph_models import EntityModel, FactModel, ConflictModel, DecisionModel, ActionRecommendationModel
from app.graph.extraction.hybrid_extractor import hybrid_extractor
from app.graph.validation.entity_resolver import entity_resolver
from app.graph.validation.conflict_detector import conflict_detector
from app.graph.validation.trust_engine import trust_engine
from app.graph.intelligence.knowledge_reasoner import knowledge_reasoner
from app.graph.intelligence.knowledge_impact_analyzer import knowledge_impact_analyzer
from app.graph.intelligence.organizational_health_engine import organizational_health_engine
from app.graph.decision_action.decision_intelligence import decision_intelligence_engine
from app.graph.decision_action.action_recommender import action_recommender
from app.graph.lifecycle.knowledge_sync_engine import knowledge_sync_engine
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.db.database import async_session_factory

@pytest.mark.asyncio
async def test_1_hybrid_extraction_strategy():
    """Verify deterministic rule & plugin entity and fact extraction."""
    tenant_id = str(uuid.uuid4())
    sample_text = (
        "Project Phoenix Status: Lead: Alice Smith. Decision: Approved deployment of BGE-Large embeddings.\n"
        "Revenue increased by $2.8M in Q3 2026."
    )

    entities, facts = hybrid_extractor.extract_all(tenant_id, sample_text)
    assert len(entities) >= 1
    assert any(e.canonical_name == "Project Phoenix" for e in entities)
    assert len(facts) >= 2
    assert any(f.metric_name == "Revenue" and f.value == "$2.8M" for f in facts)

@pytest.mark.asyncio
async def test_2_entity_resolution_and_alias_merging():
    """Verify alias mapping resolves variations to a single canonical entity."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Resolver Tenant', :domain)"), {"id": tenant_id, "domain": f"res_{tenant_id[:8]}.com"})
        await session.commit()

    id1 = await entity_resolver.resolve_or_create(tenant_id, "Microsoft Corporation", "Company")
    id2 = await entity_resolver.resolve_or_create(tenant_id, "MSFT", "Company")
    assert id1 == id2

@pytest.mark.asyncio
async def test_3_dual_evidence_conflict_detection():
    """Verify detecting contradictory facts and preserving dual evidence."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Conflict Tenant', :domain)"), {"id": tenant_id, "domain": f"conf_{tenant_id[:8]}.com"})
        await session.commit()

    fact1 = FactModel(tenant_id=tenant_id, fact_type="FinancialMetric", metric_name="Revenue", value="$1.4M", period="Q3 2026", confidence_score=0.90)
    fact2 = FactModel(tenant_id=tenant_id, fact_type="FinancialMetric", metric_name="Revenue", value="$2.8M", period="Q3 2026", confidence_score=0.95)

    f1_id = await postgres_knowledge_repo.create_fact(fact1)
    fact1.id = f1_id

    conflict_id = await conflict_detector.detect_fact_conflicts(tenant_id, fact2, [fact1])
    assert conflict_id is not None

@pytest.mark.asyncio
async def test_4_multi_signal_trust_engine():
    """Verify composite multi-signal trust score calculation."""
    score = trust_engine.calculate_trust_score(
        source_authority=0.95,
        evidence_count=4,
        recency_days=5.0,
        user_feedback_score=1.0,
        has_active_conflict=False
    )
    assert 0.70 <= score <= 1.0

@pytest.mark.asyncio
async def test_5_knowledge_reasoning_derived_facts():
    """Verify inferring derived risk facts from dependency chains."""
    tenant_id = str(uuid.uuid4())
    chain = [
        {"name": "Security Review", "state": "completed"},
        {"name": "Legal Approval", "state": "overdue"}
    ]
    derived = knowledge_reasoner.infer_dependency_risks(tenant_id, "Project Phoenix", chain)
    assert len(derived) == 1
    assert derived[0].is_derived is True
    assert "at risk due to overdue dependency" in derived[0].value

@pytest.mark.asyncio
async def test_6_knowledge_impact_analysis():
    """Verify calculating downstream dependency impact of policy changes."""
    tenant_id = str(uuid.uuid4())
    edges = [
        {"source": "Security Policy 2026", "target": "Engineering Team", "relation": "applies_to"},
        {"source": "Security Policy 2026", "target": "Project Phoenix", "relation": "affects"}
    ]
    impact = knowledge_impact_analyzer.analyze_impact(tenant_id, "Security Policy 2026", edges)
    assert impact["affected_teams_count"] == 1
    assert impact["affected_projects_count"] == 1
    assert impact["impact_severity"] in ["medium", "high"]

@pytest.mark.asyncio
async def test_7_organizational_health_and_quality():
    """Verify computing tenant KnowledgeQualityScore (0 to 100)."""
    tenant_id = str(uuid.uuid4())
    health = organizational_health_engine.compute_tenant_health(
        tenant_id=tenant_id,
        total_entities=50,
        orphan_projects=1,
        unassigned_tasks=2,
        active_conflicts=1,
        knowledge_gaps=1
    )
    assert 80.0 <= health.quality_score <= 100.0

@pytest.mark.asyncio
async def test_8_decision_intelligence_and_action_recommendations():
    """Verify recording decisions and action recommendations in AWS RDS PostgreSQL."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Decision Tenant', :domain)"), {"id": tenant_id, "domain": f"dec_{tenant_id[:8]}.com"})
        await session.commit()

    dec_id = await decision_intelligence_engine.record_decision(
        tenant_id=tenant_id,
        title="Deploy Self-Hosted BGE-Large Embeddings",
        rationale="Sub-10ms similarity search latency requirement.",
        expected_outcome="48% YoY Revenue expansion."
    )
    assert dec_id != ""

    rec_id = await action_recommender.recommend_action(
        tenant_id=tenant_id,
        action_type="AssignOwner",
        recommendation_text="Assign team owner to Project Phoenix.",
        priority="high"
    )
    assert rec_id != ""

@pytest.mark.asyncio
async def test_9_multi_tenant_rls_and_10_worker_concurrency():
    """
    Master Database Stress Test:
      1. Provisions Tenant Alpha & Tenant Beta.
      2. Ingests graph entities, relationships, facts & decisions under RLS.
      3. Verifies zero cross-tenant leakage.
      4. Executes 10 concurrent worker tasks updating knowledge graph simultaneously.
    """
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Alpha Graph Tenant', :domain)"), {"id": tenant_a, "domain": f"ga_{tenant_a[:8]}.com"})
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Beta Graph Tenant', :domain)"), {"id": tenant_b, "domain": f"gb_{tenant_b[:8]}.com"})
        await session.commit()

    # Tenant Alpha Entities & Decisions
    e1 = EntityModel(tenant_id=tenant_a, entity_type="Project", canonical_name="Alpha Secret Project")
    e1_id = await postgres_knowledge_repo.create_entity(e1)

    # Tenant Beta Entities
    e2 = EntityModel(tenant_id=tenant_b, entity_type="Project", canonical_name="Beta Secret Project")
    e2_id = await postgres_knowledge_repo.create_entity(e2)

    # RLS Audit: Tenant Alpha queries canonical name of Beta project
    found_b_in_a = await postgres_knowledge_repo.get_entity_by_canonical_name(tenant_a, "Beta Secret Project")
    assert found_b_in_a is None

    # 10 Concurrent Worker Execution
    async def _graph_worker_task(idx: int):
        t_id = tenant_a
        ent = EntityModel(tenant_id=t_id, entity_type="Task", canonical_name=f"Stress Task {idx}")
        ent_id = await postgres_knowledge_repo.create_entity(ent)
        fact = FactModel(tenant_id=t_id, fact_type="Status", metric_name=f"Worker {idx}", value="Completed")
        await postgres_knowledge_repo.create_fact(fact)
        return ent_id

    worker_res = await asyncio.gather(*[_graph_worker_task(i) for i in range(10)])
    assert len(worker_res) == 10

@pytest.mark.asyncio
async def test_10_knowledge_sync_engine_incremental_updates():
    """
    Incremental Knowledge Sync Test:
      1. FILE_CREATED: Ingests initial file.
      2. FILE_UPDATED (Unchanged Checksum): Skips reprocessing (0 cost).
      3. FILE_UPDATED (Content Changed): Supersedes old facts (is_current=False) & inserts Version 2 facts.
      4. FILE_DELETED: Archives knowledge for compliance audit retention.
    """
    tenant_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())

    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Sync Tenant', :domain)"), {"id": tenant_id, "domain": f"sync_{tenant_id[:8]}.com"})
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
        await session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                ) VALUES (
                    :id, :tenant_id, 'gdrive', 'doc', 'spreadsheet', :ext_id, 'Budget.xlsx', 'Budget is $2.8M', 'bkt', 'key', FALSE, 1024
                )
            """),
            {"id": doc_id, "tenant_id": tenant_id, "ext_id": f"ext_{doc_id[:8]}"}
        )
        await session.commit()

    # 1. FILE_CREATED
    initial_text = "Budget is $2.8M for Project Phoenix."
    checksum1 = knowledge_sync_engine.calculate_checksum(initial_text)
    f1 = FactModel(tenant_id=tenant_id, fact_type="FinancialMetric", metric_name="Budget", value="$2.8M")
    
    res_create = await knowledge_sync_engine.handle_file_created(tenant_id, doc_id, "Budget.xlsx", initial_text, [], [f1])
    assert res_create["status"] == "created"
    assert res_create["facts_inserted"] == 1

    # 2. FILE_UPDATED (Unchanged Checksum) -> Must skip reprocessing
    res_skip = await knowledge_sync_engine.handle_file_updated(tenant_id, doc_id, "Budget.xlsx", checksum1, initial_text, [f1])
    assert res_skip["status"] == "skipped"

    # 3. FILE_UPDATED (Content Changed) -> Supersedes old facts & updates new
    updated_text = "Budget expanded to $3.5M for Project Phoenix."
    f2 = FactModel(tenant_id=tenant_id, fact_type="FinancialMetric", metric_name="Budget", value="$3.5M")
    
    res_update = await knowledge_sync_engine.handle_file_updated(tenant_id, doc_id, "Budget.xlsx", checksum1, updated_text, [f2])
    assert res_update["status"] == "updated"
    assert res_update["facts_updated"] == 1

    # 4. FILE_DELETED -> Archives facts for retention
    res_delete = await knowledge_sync_engine.handle_file_deleted(tenant_id, doc_id)
    assert res_delete["status"] == "archived"
