"""Real-data test for graph-aware context enrichment — 2026-08-20.

Pins down a real bug found while verifying this feature: the enrichment code in
conversation_service.py originally used field names (relationship_type, target_name,
source_name) that don't match what postgres_knowledge_repo.get_relationships_for_entity_name
actually returns (source, target, relation) — it would have silently rendered every
graph fact as "RELATED_TO unknown" instead of the real relationship. Caught by running
this exact lookup against real DB data before declaring it done, not by assuming the
guessed field names were right.

This test exercises the same real calls conversation_service.py's graph-enrichment
block makes (get_entity_by_canonical_name, get_relationships_for_entity_name) against
a document/entity/relationship set that mirrors what a real connector's extract_graph()
+ ingestion_router.py would produce, and asserts the real relationship type and real
target name come back correctly — not "RELATED_TO unknown".
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.processors.ingestion_pipeline import chunk_embed_and_store
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.domain.graph_models import EntityModel, RelationshipModel


@pytest.mark.asyncio
async def test_graph_facts_for_retrieved_document_use_real_field_names():
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": "Graph Enrichment Test", "d": f"graph-test-{tenant_id[:8]}.company.com"},
        )
        await session.commit()

    doc_id = str(uuid.uuid4())
    doc_title = "Infra Review Notes"
    content = "Quarterly infrastructure review: the payments service migration is on track for completion by end of September."
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type,
                    external_id, title, content, s3_bucket, s3_key, is_compressed, file_size_bytes)
                VALUES (:id, :t, 'slack', 'chat_message', 'message', :ext, :title, :content, 'b', 'k', TRUE, :sz)
            """),
            {"id": doc_id, "t": tenant_id, "ext": "ext1", "title": doc_title, "content": content, "sz": len(content)},
        )
        await session.commit()

    result = await chunk_embed_and_store(tenant_id=tenant_id, document_id=doc_id, full_text=content, resource_category="chat_message")
    assert result["status"] == "completed"

    # Mirrors what a real connector's extract_graph() + ingestion_router.py produces.
    doc_entity_id = await postgres_knowledge_repo.create_entity(EntityModel(
        tenant_id=tenant_id, entity_type="document", canonical_name=doc_title, attributes={"title": doc_title}))
    person_entity_id = await postgres_knowledge_repo.create_entity(EntityModel(
        tenant_id=tenant_id, entity_type="person", canonical_name="U_PRIYA", attributes={}))
    await postgres_knowledge_repo.create_relationship(
        RelationshipModel(tenant_id=tenant_id, source_entity_id=doc_entity_id, target_entity_id=person_entity_id,
            relation_type="AUTHORED_BY", attributes={}),
        document_id=doc_id,
    )

    # Real retrieval, same as conversation_service.py's live path.
    raw = await hybrid_retriever.search(query="payments service migration status", tenant_id=tenant_id, top_k=5, user_id="U_PRIYA")
    chunks = raw.get("chunks", [])
    assert len(chunks) > 0, "The real document must be retrieved for this query."
    doc_titles = {c.get("doc_title") for c in chunks}
    assert doc_title in doc_titles

    # Exact same enrichment logic as conversation_service.py's graph-aware block.
    entity = await postgres_knowledge_repo.get_entity_by_canonical_name(tenant_id, doc_title)
    assert entity is not None, "A real graph entity must exist for the retrieved document."

    edges = await postgres_knowledge_repo.get_relationships_for_entity_name(tenant_id, doc_title)
    assert len(edges) > 0
    edge = edges[0]
    other = edge["target"] if edge["source"] == doc_title else edge["source"]
    fact_line = f"- \"{doc_title}\" {edge['relation']} {other}"

    assert "AUTHORED_BY" in fact_line, f"Real relationship type must appear, got: {fact_line!r}"
    assert "U_PRIYA" in fact_line, f"Real target entity must appear, got: {fact_line!r}"
    assert "RELATED_TO" not in fact_line and "unknown" not in fact_line, (
        f"Must never silently fall back to the generic placeholder when real data exists, got: {fact_line!r}"
    )
