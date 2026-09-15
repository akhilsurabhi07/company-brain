"""
Real test for the keyword/BM25 arm of hybrid retrieval.

KeywordRetriever.retrieve() was a hardcoded stub that always returned [] — hybrid
ranking silently ran vector-only in production. This pins the real behavior: a
Postgres full-text search over document_chunks.text_search_vector, tenant-scoped,
that correctly surfaces a specific-ID query (the exact case pure vector similarity
struggles with among near-duplicate documents).
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.db.retrievers.context_builder import keyword_retriever

TEST_TENANT = "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_keyword_retriever_finds_real_tenant_scoped_match():
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'KW Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"kwtest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :tid, 'upload', 'engineering', 'doc', :ext, 'Keyword Retrieval Fix Test Doc', 'test content', 'test-bucket', :s3key, 12)
            """),
            {"id": doc_id, "tid": TEST_TENANT, "ext": f"kwtest-{chunk_id[:8]}", "s3key": f"kwtest-{chunk_id[:8]}"},
        )
        await session.execute(
            text("""
                INSERT INTO document_chunks (id, tenant_id, document_id, chunk_index, text_content, token_count)
                VALUES (:id, :tid, :doc_id, 0, :content, 20)
            """),
            {
                "id": chunk_id,
                "tid": TEST_TENANT,
                "doc_id": doc_id,
                "content": "Ticket ZX-88421 was assigned to the Nightwatch rollout squad for review.",
            },
        )
        await session.commit()

    try:
        # A specific alphanumeric ID a vector-only search could plausibly miss/confuse —
        # exactly the case keyword/BM25 matching exists to catch.
        results = await keyword_retriever.retrieve(TEST_TENANT, "ZX-88421 Nightwatch rollout", top_k=5)
        assert len(results) >= 1, "keyword retriever returned no matches for real, present content — still a stub?"
        assert any(str(r["chunk_id"]) == chunk_id for r in results)
        assert results[0]["similarity_score"] > 0

        # Cross-tenant isolation: a different tenant must never see this chunk via keyword search.
        other_tenant_results = await keyword_retriever.retrieve(
            "33333333-3333-3333-3333-333333333333", "ZX-88421 Nightwatch rollout", top_k=5
        )
        assert not any(str(r["chunk_id"]) == chunk_id for r in other_tenant_results)
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM document_chunks WHERE id = :id"), {"id": chunk_id})
            await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
            await session.commit()
