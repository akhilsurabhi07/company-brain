"""
Module 4 — Master Complex & Stress Test Suite
==============================================
Rigorous enterprise test suite for Module 4 GraphRAG Knowledge Retrieval Engine.
Evaluates multi-tenant RLS isolation, cyclic graph traversal safety, multi-intent synthesis,
contradiction resolution, knowledge gap classification, concurrent retrieval stress,
and tenant-isolated semantic caching.
"""
import uuid
import time
import asyncio
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext
from app.retrieval.implementations.query_understanding import QueryUnderstandingEngine
from app.retrieval.implementations.knowledge_execution_planner import KnowledgeExecutionPlanner
from app.retrieval.implementations.retrieval_policy_engine import retrieval_policy_engine
from app.retrieval.implementations.graph_traversal import graph_traversal_service
from app.retrieval.implementations.knowledge_graph_retriever import KnowledgeGraphRetriever
from app.retrieval.fusion.strategies.rrf import apply_rrf
from app.retrieval.fusion.strategies.graph_priority import apply_graph_priority_fusion
from app.retrieval.implementations.evidence_orchestrator import evidence_orchestrator
from app.retrieval.implementations.graphrag_reranker import graphrag_reranker
from app.retrieval.implementations.knowledge_synthesizer import knowledge_synthesizer
from app.retrieval.implementations.knowledge_validator import knowledge_validator
from app.retrieval.implementations.knowledge_gap_detector import knowledge_gap_detector
from app.retrieval.implementations.evidence_quality_engine import evidence_quality_engine
from app.retrieval.infrastructure.cache.semantic_retrieval_cache import semantic_cache
from app.retrieval.retrieval_service import knowledge_retrieval_service
from app.domain.graph_models import EntityModel, FactModel, RelationshipModel, DecisionModel
from app.db.postgres_knowledge_repo import postgres_knowledge_repo

@pytest.mark.asyncio
async def test_complex_multitenant_rls_graphrag_isolation():
    """Complex Test 1: Evaluates strict RLS boundary enforcement under identical entity names across 2 tenants."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant A Corp', :domain)"), {"id": tenant_a, "domain": f"ta_{tenant_a[:8]}.com"})
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant B Corp', :domain)"), {"id": tenant_b, "domain": f"tb_{tenant_b[:8]}.com"})
        await session.commit()

    # Tenant A seeds "Project Titan" -> "Security Audit"
    e_a1 = EntityModel(tenant_id=tenant_a, entity_type="Project", canonical_name="Project Titan")
    e_a2 = EntityModel(tenant_id=tenant_a, entity_type="Requirement", canonical_name="Security Audit")
    e_a1_id = await postgres_knowledge_repo.create_entity(e_a1)
    e_a2_id = await postgres_knowledge_repo.create_entity(e_a2)
    rel_a = RelationshipModel(tenant_id=tenant_a, source_entity_id=e_a1_id, relation_type="requires", target_entity_id=e_a2_id, weight=0.99)
    await postgres_knowledge_repo.create_relationship(rel_a)

    # Tenant B seeds "Project Titan" -> "Financial Audit"
    e_b1 = EntityModel(tenant_id=tenant_b, entity_type="Project", canonical_name="Project Titan")
    e_b2 = EntityModel(tenant_id=tenant_b, entity_type="Requirement", canonical_name="Financial Audit")
    e_b1_id = await postgres_knowledge_repo.create_entity(e_b1)
    e_b2_id = await postgres_knowledge_repo.create_entity(e_b2)
    rel_b = RelationshipModel(tenant_id=tenant_b, source_entity_id=e_b1_id, relation_type="requires", target_entity_id=e_b2_id, weight=0.95)
    await postgres_knowledge_repo.create_relationship(rel_b)

    # Query for Tenant A
    context_a = await knowledge_retrieval_service.execute_retrieval(tenant_id=tenant_a, query="Project Titan requirements")
    assert context_a.schema_version == "1.0"
    # Check that retrieved relationships ONLY mention Security Audit, NOT Financial Audit
    rel_names_a = [f"{r.source_name} -> {r.target_name}" for r in context_a.graph_relationships]
    for rel_str in rel_names_a:
        assert "Financial Audit" not in rel_str

    # Query for Tenant B
    context_b = await knowledge_retrieval_service.execute_retrieval(tenant_id=tenant_b, query="Project Titan requirements")
    assert context_b.schema_version == "1.0"
    rel_names_b = [f"{r.source_name} -> {r.target_name}" for r in context_b.graph_relationships]
    for rel_str in rel_names_b:
        assert "Security Audit" not in rel_str

@pytest.mark.asyncio
async def test_complex_circular_graph_traversal_depth_limit():
    """Complex Test 2: Evaluates graph traversal resilience under cyclic dependencies (Node A -> Node B -> Node C -> Node A)."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Cyclic Tenant', :domain)"), {"id": tenant_id, "domain": f"cyc_{tenant_id[:8]}.com"})
        await session.commit()

    e1 = EntityModel(tenant_id=tenant_id, entity_type="Service", canonical_name="Service Alpha")
    e2 = EntityModel(tenant_id=tenant_id, entity_type="Service", canonical_name="Service Beta")
    e3 = EntityModel(tenant_id=tenant_id, entity_type="Service", canonical_name="Service Gamma")

    id1 = await postgres_knowledge_repo.create_entity(e1)
    id2 = await postgres_knowledge_repo.create_entity(e2)
    id3 = await postgres_knowledge_repo.create_entity(e3)

    # Create cycle: id1 -> id2 -> id3 -> id1
    await postgres_knowledge_repo.create_relationship(RelationshipModel(tenant_id=tenant_id, source_entity_id=id1, relation_type="calls", target_entity_id=id2))
    await postgres_knowledge_repo.create_relationship(RelationshipModel(tenant_id=tenant_id, source_entity_id=id2, relation_type="calls", target_entity_id=id3))
    await postgres_knowledge_repo.create_relationship(RelationshipModel(tenant_id=tenant_id, source_entity_id=id3, relation_type="calls", target_entity_id=id1))

    # Traversal should complete without infinite recursion
    traversal_res = await graph_traversal_service.traverse(tenant_id, "Service Alpha", max_hops=3)
    assert "seed_entity" in traversal_res
    assert len(traversal_res["relationships"]) >= 1

@pytest.mark.asyncio
async def test_complex_multi_intent_execution_plan_synthesis():
    """Complex Test 3: Evaluates multi-intent query understanding and execution planning."""
    tenant_id = str(uuid.uuid4())
    ctx = RetrievalPipelineContext(
        correlation_id=f"test_{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        query="Why is Project Omega delayed due to legal compliance issues and what is the budget impact for Q4?"
    )

    query_intel = QueryUnderstandingEngine()
    planner = KnowledgeExecutionPlanner()

    analysis = await query_intel.analyze(ctx)
    assert analysis.intent in ["RiskAnalysis", "FinancialMetric", "Compliance", "General"]
    assert any(c.intent_name == "RiskAnalysis" for c in analysis.ranked_intents)
    assert "Project Omega" in analysis.entities

    plan = await planner.plan(ctx, analysis)
    assert "dense" in plan.strategies
    assert "graph" in plan.strategies
    assert plan.hop_depth >= 2
    assert plan.resource_budget_ms > 0

@pytest.mark.asyncio
async def test_complex_contradictory_evidence_synthesizer():
    """Complex Test 4: Evaluates KnowledgeSynthesizer timeline extraction and contradiction handling."""
    candidates = [
        Candidate(id="c1", item_type="dense_chunk", content="Project Deadline updated to August 2026 during Slack sync.", score=0.88, source_metadata={"period": "Q2 2026", "source_system": "Slack"}),
        Candidate(id="c2", item_type="graph_fact", content="Fact: Project Deadline = October 2026", score=0.95, source_metadata={"period": "Q3 2026", "source_system": "Jira"}),
        Candidate(id="c3", item_type="graph_decision", content="Decision: Final approval granted on July 15 2026", score=0.92, source_metadata={"period": "Q3 2026", "source_system": "Confluence"})
    ]

    synth_res = knowledge_synthesizer.synthesize(candidates)
    assert len(synth_res["timelines"]) >= 2
    # Verify timeline entries are extracted and structured
    timeline_texts = [t["event"] for t in synth_res["timelines"]]
    assert any("August" in text or "October" in text or "Deadline" in text for text in timeline_texts)

@pytest.mark.asyncio
async def test_complex_knowledge_gap_detection_unresolved_dependencies():
    """Complex Test 5: Evaluates KnowledgeGapDetector identifying multiple missing architectural/ownership fields."""
    candidates = [
        Candidate(id="c1", item_type="dense_chunk", content="Project Phoenix has no assigned technical lead.", score=0.80),
        Candidate(id="c2", item_type="graph_fact", content="Fact: Legal Approval status = Pending", score=0.85),
        Candidate(id="c3", item_type="dense_chunk", content="Unassigned security audit pending review.", score=0.75)
    ]

    gaps = knowledge_gap_detector.detect_gaps(candidates)
    assert len(gaps) >= 1
    gap_types = [g.gap_type for g in gaps]
    assert "MissingOwner" in gap_types or "UnresolvedDependency" in gap_types

@pytest.mark.asyncio
async def test_complex_concurrent_retrieval_service_stress():
    """Complex Test 6: Evaluates high concurrency (10 parallel requests across 5 distinct tenants)."""
    tenants = [str(uuid.uuid4()) for _ in range(5)]
    async with async_session_factory() as session:
        for t_id in tenants:
            await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain)"), {"id": t_id, "name": f"Stress Tenant {t_id[:4]}", "domain": f"st_{t_id[:8]}.com"})
        await session.commit()

    # Seed 1 entity for each tenant
    for t_id in tenants:
        await postgres_knowledge_repo.create_entity(EntityModel(tenant_id=t_id, entity_type="Project", canonical_name=f"Project {t_id[:4]}"))

    async def execute_query(t_id, q_idx):
        return await knowledge_retrieval_service.execute_retrieval(
            tenant_id=t_id,
            query=f"Status for Project {t_id[:4]} query {q_idx}"
        )

    tasks = []
    for i in range(10):
        t_id = tenants[i % len(tenants)]
        tasks.append(execute_query(t_id, i))

    t0 = time.time()
    results = await asyncio.gather(*tasks)
    total_ms = (time.time() - t0) * 1000.0

    assert len(results) == 10
    for res in results:
        assert res.schema_version == "1.0"
        assert res.confidence.overall >= 0.50

    print(f"\n--- [CONCURRENCY STRESS] Executed 10 Parallel Retrievals across 5 Tenants in {total_ms:.2f} ms ---")

@pytest.mark.asyncio
async def test_complex_semantic_cache_tenant_partitioning():
    """Complex Test 7: Evaluates strict tenant boundary isolation in Semantic Retrieval Cache."""
    tenant_1 = str(uuid.uuid4())
    tenant_2 = str(uuid.uuid4())

    q = "What is the secret deployment key?"
    val_1 = {"secret": "Key_Tenant_1"}
    val_2 = {"secret": "Key_Tenant_2"}

    await semantic_cache.set(tenant_1, q, val_1)
    await semantic_cache.set(tenant_2, q, val_2)

    res_1 = await semantic_cache.get(tenant_1, q)
    res_2 = await semantic_cache.get(tenant_2, q)

    assert res_1["secret"] == "Key_Tenant_1"
    assert res_2["secret"] == "Key_Tenant_2"

@pytest.mark.asyncio
async def test_complex_evidence_quality_and_confidence_scoring():
    """Complex Test 8: Evaluates composite confidence calculations and evidence quality engine."""
    c_high = Candidate(id="c_h", item_type="graph_fact", content="Fact: Compliance = Verified", score=0.98, source_metadata={"confidence_score": 0.99})
    c_low = Candidate(id="c_l", item_type="dense_chunk", content="Random unverified note from chat", score=0.45, source_metadata={"confidence_score": 0.40})

    conf_h, qual_h, citations_h = evidence_quality_engine.evaluate_quality_and_citations([c_high])
    conf_l, qual_l, citations_l = evidence_quality_engine.evaluate_quality_and_citations([c_low])

    assert qual_h.authority_score >= 0.90
    assert conf_h.overall >= conf_l.overall
    assert len(citations_h) == 1
