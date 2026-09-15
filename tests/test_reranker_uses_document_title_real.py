"""
Real test for a retrieval-miss root-caused and fixed 2026-08-21: a real Jira
ticket ("PROJ-101: Configure Multi-Tenant Row Level Security in Postgres") was
rejected by the cross-encoder reranker even for a query worded almost exactly
like the ticket's own title, because the reranker only ever saw the bare chunk
CONTENT ("Ensure all database sessions execute SET LOCAL app.current_tenant_id
before running queries.") — the actual topic keywords ("row level security",
"Postgres", "multi-tenant") live only in the document TITLE, never repeated in
the terse body text. This is a structural pattern for ticket/PR/meeting-style
documents generally, not a one-off.

Confirmed directly against the real model: content-only scored -10.95
(rejected, well under the -5.0 threshold); title+content scored +5.84 (clearly
accepted). A genuinely irrelevant control query against the same chunk (title
prefixed) still scored -11.48, unchanged from -11.46 content-only — confirming
the fix restores missing context rather than introducing false positives.

Fixed by prefixing each chunk's content with its real document title before
handing it to the cross-encoder.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever

TEST_TENANT = "99999999-9999-9999-9999-999999999901"


@pytest.mark.asyncio
async def test_title_only_keywords_still_find_the_real_chunk():
    """Positive case: the query's keywords live only in the document title, not
    in the chunk body — this must still retrieve the real chunk."""
    doc_id = str(uuid.uuid4())
    title = "TICKET-77: Configure Multi-Tenant Row Level Security in Postgres"
    body = "Ensure all database sessions execute SET LOCAL app.current_tenant_id before running queries."

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Rerank Title Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"reranktitletest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :tid, 'jira', 'ticket', 'issue', :ext, :title, :content, 'b', :s3key, 4)
            """),
            {"id": doc_id, "tid": TEST_TENANT, "ext": f"reranktitletest-{doc_id[:8]}", "s3key": f"reranktitletest-{doc_id[:8]}", "title": title, "content": body},
        )
        await session.commit()

    from app.processors.semantic_chunker import SemanticChunker
    from app.embeddings.bge_embedder import bge_embedder
    from app.db.chunk_vector_repo import chunk_vector_repo

    chunks = SemanticChunker().chunk_document(tenant_id=TEST_TENANT, document_id=doc_id, full_text=body, resource_category="ticket")
    embeddings = bge_embedder.embed_texts([c.text_content for c in chunks])
    await chunk_vector_repo.save_chunks_and_embeddings(tenant_id=TEST_TENANT, document_id=doc_id, chunks=chunks, embeddings=embeddings)

    try:
        res = await hybrid_retriever.search(
            query="What is the status of configuring multi-tenant row level security in Postgres?",
            tenant_id=TEST_TENANT, top_k=5, user_id="u1",
        )
        chunks_out = res.get("chunks", []) if isinstance(res, dict) else res
        assert len(chunks_out) > 0, "the real ticket must be found even though its title-only keywords aren't in the chunk body"
        assert any("TICKET-77" in (c.get("doc_title") or "") for c in chunks_out)

        # Negative control: a genuinely unrelated query against the same tenant/content
        # must still be rejected — title-prefixing must not cause false positives.
        res2 = await hybrid_retriever.search(
            query="What's our marketing budget for next quarter?",
            tenant_id=TEST_TENANT, top_k=5, user_id="u1",
        )
        chunks_out2 = res2.get("chunks", []) if isinstance(res2, dict) else res2
        assert len(chunks_out2) == 0, "an unrelated query must not be accepted just because a title was prefixed"
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM document_chunks WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM embeddings WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
            await session.commit()
