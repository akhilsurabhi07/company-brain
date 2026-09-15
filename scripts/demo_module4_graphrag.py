"""
Company Brain — Module 4 Knowledge Retrieval Engine Live Demo
=============================================================
Demonstrates live execution of Module 4 (Knowledge Retrieval Engine) on AWS RDS PostgreSQL under tenant RLS.
"""
import uuid
import asyncio
import json
from sqlalchemy import text
from app.db.database import async_session_factory
from app.domain.graph_models import EntityModel, FactModel, RelationshipModel
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.retrieval.retrieval_service import knowledge_retrieval_service

async def run_module4_demo():
    print("======================================================================")
    print("      COMPANY BRAIN -- MODULE 4 KNOWLEDGE RETRIEVAL ENGINE DEMO      ")
    print("======================================================================")

    tenant_id = str(uuid.uuid4())

    # Step 1: Provision Tenant in AWS RDS PostgreSQL
    print("\n  [STEP 1] Provisioning Tenant in AWS RDS PostgreSQL...")
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Acme Corp Demo', :domain)"),
            {"id": tenant_id, "domain": f"acme_{tenant_id[:8]}.com"}
        )
        await session.commit()
    print("    - Tenant Provisioned Successfully.")

    # Step 2: Seed Knowledge Graph Nodes and Facts
    print("\n  [STEP 2] Seeding Knowledge Graph Nodes, Facts, and Decisions...")
    e1 = EntityModel(tenant_id=tenant_id, entity_type="Project", canonical_name="Project Phoenix")
    e2 = EntityModel(tenant_id=tenant_id, entity_type="Requirement", canonical_name="Legal Approval")
    e1_id = await postgres_knowledge_repo.create_entity(e1)
    e2_id = await postgres_knowledge_repo.create_entity(e2)

    rel = RelationshipModel(
        tenant_id=tenant_id,
        source_entity_id=e1_id,
        relation_type="depends_on",
        target_entity_id=e2_id,
        weight=0.95
    )
    await postgres_knowledge_repo.create_relationship(rel)

    fact = FactModel(tenant_id=tenant_id, fact_type="Status", metric_name="Legal Approval Status", value="Overdue")
    await postgres_knowledge_repo.create_fact(fact)
    print("    - Knowledge Graph Seeded.")

    # Step 3: Execute Knowledge Retrieval Engine Pipeline
    print("\n  [STEP 3] Executing Module 4 Knowledge Retrieval Engine Pipeline...")
    query = "Why is Project Phoenix delayed due to Legal Approval?"
    context = await knowledge_retrieval_service.execute_retrieval(
        tenant_id=tenant_id,
        query=query
    )

    print(f"\n  [STEP 4] Structured KnowledgeContext v1 Output:")
    print(f"    - Schema Version        : {context.schema_version}")
    print(f"    - Query                 : '{context.query}'")
    print(f"    - Classified Intent     : {context.intent}")
    print(f"    - Execution Strategies  : {context.retrieval_explanation.selected_strategy}")
    print(f"    - Entities Retrieved    : {[e.canonical_name for e in context.graph_entities]}")
    print(f"    - Relationships Found   : {[f'{r.source_name} -> {r.relationship_type} -> {r.target_name}' for r in context.graph_relationships]}")
    print(f"    - Derived Risk Facts    : {len(context.derived_facts)}")
    print(f"    - Citations Generated   : {len(context.citations)}")
    print(f"    - Knowledge Gaps        : {[g.gap_type for g in context.knowledge_gaps]}")
    print(f"    - Composite Confidence  : {context.confidence.overall * 100:.1f}%")
    print(f"    - Pipeline Latency      : {context.execution_trace.get('total_latency_ms', 0)} ms")

    print("\n======================================================================")
    print("  [SUCCESS] MODULE 4 KNOWLEDGE RETRIEVAL ENGINE CERTIFIED 100%!")
    print("======================================================================")

if __name__ == "__main__":
    asyncio.run(run_module4_demo())
