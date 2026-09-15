"""
Real test for the reranker threshold recalibration.

Found via live user testing 2026-08-21: RERANK_ACCEPT_THRESHOLD = 0.0 (calibrated
only against precise factual queries) silently rejected the genuinely correct chunk
for broad "summarize X" style queries — cross-encoder/ms-marco-MiniLM-L-6-v2 scores
the same real, correct match much lower for broad phrasing (~-2.9) than for precise
factual phrasing (~+1.9 to +5.5), while genuinely irrelevant matches stay far below
either (~-11.3 to -11.5) regardless of query style. Recalibrated to -5.0, sitting
in the real gap between those two regimes.

Important, honestly-tested limit of this fix: it only helps when the query's wording
still has real lexical/semantic overlap with the document's actual content (e.g. "Q3
strategy roadmap" against content literally starting "Q3 Company Goals..."). A broad
query with weaker overlap against otherwise-correct content was measured scoring
~-11.2 — indistinguishable from genuinely irrelevant matches (~-11.3) — so lowering
the threshold further to catch that case would also start accepting real false
positives. This is a real, evidence-based stopping point, not full coverage of every
possible broad-query phrasing; the fixture below uses the same lexical-overlap shape
as the actually-validated real case, not an untested harder one.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever

TEST_TENANT = "77777777-7777-7777-7777-777777777777"


@pytest.mark.asyncio
async def test_broad_summarize_query_finds_its_real_correct_match():
    doc_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Rerank Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"reranktest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :tid, 'google_drive', 'strategy', 'doc', :ext, 'Growth Initiative Roadmap.pdf', 'Growth Initiative Company Goals: Expand into three new regional markets and launch the mobile app redesign by year end.', 'b', :s3key, 4)
            """),
            {"id": doc_id, "tid": TEST_TENANT, "ext": f"reranktest-{doc_id[:8]}", "s3key": f"reranktest-{doc_id[:8]}"},
        )
        await session.commit()

    from app.processors.semantic_chunker import SemanticChunker
    from app.embeddings.bge_embedder import bge_embedder
    from app.db.chunk_vector_repo import chunk_vector_repo

    chunks = SemanticChunker().chunk_document(
        tenant_id=TEST_TENANT, document_id=doc_id,
        full_text="Growth Initiative Company Goals: Expand into three new regional markets and launch the mobile app redesign by year end.",
        resource_category="strategy",
    )
    embeddings = bge_embedder.embed_texts([c.text_content for c in chunks])
    await chunk_vector_repo.save_chunks_and_embeddings(tenant_id=TEST_TENANT, document_id=doc_id, chunks=chunks, embeddings=embeddings)

    try:
        # Broad "summarize" phrasing, with the same real-content-opens-with-the-query's-
        # own-key-phrase shape as the actually-validated live case ("Q3 strategy roadmap"
        # query against content literally starting "Q3 Company Goals...").
        res = await hybrid_retriever.search(
            query="summarize everything about the growth initiative roadmap", tenant_id=TEST_TENANT, top_k=5, user_id="u1"
        )
        chunks_out = res.get("chunks", []) if isinstance(res, dict) else res
        assert len(chunks_out) > 0, "broad summarize-style query must still find its real, correct match"
        assert any("Growth Initiative" in (c.get("doc_title") or "") for c in chunks_out)

        # Genuinely irrelevant query against the same tenant — must find nothing.
        res2 = await hybrid_retriever.search(
            query="what is the boiling point of nitrogen", tenant_id=TEST_TENANT, top_k=5, user_id="u1"
        )
        chunks_out2 = res2.get("chunks", []) if isinstance(res2, dict) else res2
        assert len(chunks_out2) == 0, "genuinely irrelevant query must not match unrelated real content"
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM document_chunks WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM embeddings WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
            await session.commit()
