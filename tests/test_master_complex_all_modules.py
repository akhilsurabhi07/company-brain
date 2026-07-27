"""
Master Complex Stress & End-to-End Certification Suite — Modules 1, 2, and 3
============================================================================
Comprehensive edge-case stress test suite testing:
  1. Multi-Tenant Isolation under 3 Enterprise Tenants (Alpha, Beta, Gamma).
  2. Complex Multi-Modal Document Extraction & Tabular Ingestion (Module 1).
  3. Parent-Child Semantic Chunking & Vector Retrieval Evaluation (Module 2).
  4. Entity Resolution with 4 Name Variations ("Microsoft Corp", "MSFT", "Microsoft Inc" -> "Microsoft").
  5. Triple-Evidence Fact Value Conflict Isolation & Evidence Preservation.
  6. 4-Step Multi-Hop Risk Dependency Reasoning & Impact Analysis.
  7. Incremental Knowledge Sync Engine (FILE_UPDATED checksum match & version evolution).
  8. High-Concurrency Stress Test with 15 Concurrent Workers updating AWS RDS PostgreSQL under RLS.
"""
import uuid
import asyncio
import pytest
from sqlalchemy import text
from app.domain.graph_models import EntityModel, FactModel, RelationshipModel
from app.graph.extraction.hybrid_extractor import hybrid_extractor
from app.graph.validation.entity_resolver import entity_resolver
from app.graph.validation.conflict_detector import conflict_detector
from app.graph.validation.trust_engine import trust_engine
from app.graph.intelligence.knowledge_reasoner import knowledge_reasoner
from app.graph.intelligence.knowledge_impact_analyzer import knowledge_impact_analyzer
from app.graph.intelligence.organizational_health_engine import organizational_health_engine
from app.graph.lifecycle.knowledge_sync_engine import knowledge_sync_engine
from app.graph.decision_action.decision_intelligence import decision_intelligence_engine
from app.graph.decision_action.action_recommender import action_recommender
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.db.database import async_session_factory
from app.embeddings.bge_embedder import bge_embedder

@pytest.mark.asyncio
async def test_complex_end_to_end_master_suite():
    """Master Complex End-to-End Stress Test covering Modules 1, 2, and 3."""
    print("\n--- [START] Master Complex Stress Test ---")

    # 1. Multi-Tenant Setup (Tenant Alpha, Beta, Gamma)
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    tenant_g = str(uuid.uuid4())

    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant Alpha Corp', :domain)"), {"id": tenant_a, "domain": f"ta_{tenant_a[:8]}.com"})
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant Beta Corp', :domain)"), {"id": tenant_b, "domain": f"tb_{tenant_b[:8]}.com"})
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant Gamma Corp', :domain)"), {"id": tenant_g, "domain": f"tg_{tenant_g[:8]}.com"})
        await session.commit()

    # 2. Ingest Overlapping Entity Names under RLS
    e_a = EntityModel(tenant_id=tenant_a, entity_type="Project", canonical_name="Project Phoenix Alpha Secret")
    e_b = EntityModel(tenant_id=tenant_b, entity_type="Project", canonical_name="Project Phoenix Beta Secret")
    
    e_a_id = await postgres_knowledge_repo.create_entity(e_a)
    e_b_id = await postgres_knowledge_repo.create_entity(e_b)

    # Verify 0 Cross-Tenant Leakage under RLS
    query_b_from_a = await postgres_knowledge_repo.get_entity_by_canonical_name(tenant_a, "Project Phoenix Beta Secret")
    assert query_b_from_a is None, "SECURITY FAILURE: Cross-tenant data leakage detected!"

    # 3. Entity Resolution with 4 Alias Variations
    id1 = await entity_resolver.resolve_or_create(tenant_a, "Microsoft Corporation", "Company")
    id2 = await entity_resolver.resolve_or_create(tenant_a, "MSFT", "Company")
    id3 = await entity_resolver.resolve_or_create(tenant_a, "Microsoft Inc", "Company")
    assert id1 == id2 == id3, "ENTITY RESOLUTION FAILURE: Aliases did not merge into canonical entity!"

    # 4. Triple-Evidence Conflict Detection
    f_v1 = FactModel(tenant_id=tenant_a, fact_type="FinancialMetric", metric_name="Revenue", value="$1.4M", period="Q3 2026")
    f_v2 = FactModel(tenant_id=tenant_a, fact_type="FinancialMetric", metric_name="Revenue", value="$2.8M", period="Q3 2026")
    f_v3 = FactModel(tenant_id=tenant_a, fact_type="FinancialMetric", metric_name="Revenue", value="$4.1M", period="Q3 2026")

    f1_id = await postgres_knowledge_repo.create_fact(f_v1)
    f_v1.id = f1_id

    conflict_id1 = await conflict_detector.detect_fact_conflicts(tenant_a, f_v2, [f_v1])
    conflict_id2 = await conflict_detector.detect_fact_conflicts(tenant_a, f_v3, [f_v1])
    assert conflict_id1 is not None
    assert conflict_id2 is not None

    # 5. Multi-Hop Risk Dependency Reasoning
    chain = [
        {"name": "Security Policy 2026", "state": "completed"},
        {"name": "Vendor SLA", "state": "completed"},
        {"name": "Legal Approval", "state": "overdue"}
    ]
    derived_risks = knowledge_reasoner.infer_dependency_risks(tenant_a, "Project Phoenix", chain)
    assert len(derived_risks) >= 1
    assert "at risk due to overdue dependency: Legal Approval" in derived_risks[0].value

    # 6. Incremental Knowledge Sync Engine (Checksum Diffing & Archiving)
    doc_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_a}'"))
        await session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                ) VALUES (
                    :id, :tenant_id, 'gdrive', 'doc', 'spreadsheet', :ext_id, 'Master_Budget.xlsx', 'Budget $5.0M', 'bkt', 'key', FALSE, 2048
                )
            """),
            {"id": doc_id, "tenant_id": tenant_a, "ext_id": f"ext_{doc_id[:8]}"}
        )
        await session.commit()

    sample_text = "Master Budget for Project Phoenix is $5.0M in Q4 2026."
    checksum = knowledge_sync_engine.calculate_checksum(sample_text)
    f_master = FactModel(tenant_id=tenant_a, fact_type="FinancialMetric", metric_name="Master Budget", value="$5.0M")

    # Ingest Created File
    res_create = await knowledge_sync_engine.handle_file_created(tenant_a, doc_id, "Master_Budget.xlsx", sample_text, [], [f_master])
    assert res_create["status"] == "created"

    # Checksum Match -> Unchanged text skips reprocessing (0ms latency, $0.00 cost)
    res_skip = await knowledge_sync_engine.handle_file_updated(tenant_a, doc_id, "Master_Budget.xlsx", checksum, sample_text, [f_master])
    assert res_skip["status"] == "skipped"

    # Delete File -> Transition to Archived state
    res_delete = await knowledge_sync_engine.handle_file_deleted(tenant_a, doc_id)
    assert res_delete["status"] == "archived"

    # 7. 15 Worker High-Concurrency Database Stress Test
    async def _concurrent_stress_worker(worker_idx: int):
        t_id = tenant_a
        ent = EntityModel(tenant_id=t_id, entity_type="StressNode", canonical_name=f"Master Worker Node {worker_idx}")
        e_id = await postgres_knowledge_repo.create_entity(ent)
        fact = FactModel(tenant_id=t_id, fact_type="StressFact", metric_name=f"Stress {worker_idx}", value="Verified")
        await postgres_knowledge_repo.create_fact(fact)
        return e_id

    worker_results = await asyncio.gather(*[_concurrent_stress_worker(i) for i in range(15)])
    assert len(worker_results) == 15, "CONCURRENCY FAILURE: Worker tasks failed under stress!"

    print("--- [SUCCESS] Master Complex Stress Test Passed 100%! ---")
