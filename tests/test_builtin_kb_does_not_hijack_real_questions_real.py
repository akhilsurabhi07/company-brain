"""
Real test for a bug found via live testing 2026-08-22, on a brand-new tenant's very
first real workflow (signup -> upload -> ask): "What VPN client do we use and how do
I request access?" — whose exact answer was sitting in a document uploaded moments
earlier — got hijacked by conversation_service.py's builtin-knowledge fast-path,
which matched the bare word "vpn" anywhere in the query and returned a generic
dictionary definition ("VPN stands for Virtual Private Network...") instead of ever
attempting real retrieval against the user's own real data.

Root cause: the single-word fallback matched ANY word in a query of any length —
"vpn" wasn't even on the existing short-acronym exclusion list, but the deeper flaw
was no length gate at all. Fixed: the single-word fallback only fires for short
(<=4 word) queries now, so a real, specific, longer operational question always
reaches real retrieval.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "88888888-8888-8888-8888-888888888812"


@pytest.mark.asyncio
async def test_specific_question_using_a_common_acronym_reaches_real_retrieval_not_builtin_kb():
    doc_id = str(uuid.uuid4())
    content = "The VPN client is Tailscale; request access from IT via the #it-helpdesk Slack channel."

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Builtin KB Hijack Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"builtinkbtest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :tid, 'upload', 'onboarding', 'doc', :ext, 'Onboarding Guide.txt', :content, 'b', :s3key, 4)
            """),
            {"id": doc_id, "tid": TEST_TENANT, "ext": f"builtinkbtest-{doc_id[:8]}", "s3key": f"builtinkbtest-{doc_id[:8]}", "content": content},
        )
        await session.commit()

    from app.processors.semantic_chunker import SemanticChunker
    from app.embeddings.bge_embedder import bge_embedder
    from app.db.chunk_vector_repo import chunk_vector_repo

    chunks = SemanticChunker().chunk_document(tenant_id=TEST_TENANT, document_id=doc_id, full_text=content, resource_category="onboarding")
    embeddings = bge_embedder.embed_texts([c.text_content for c in chunks])
    await chunk_vector_repo.save_chunks_and_embeddings(tenant_id=TEST_TENANT, document_id=doc_id, chunks=chunks, embeddings=embeddings)

    try:
        service = ConversationService()
        result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="new_user", session_id="builtin-kb-hijack-session",
            user_query="What VPN client do we use and how do I request access?",
        )
        answer = result.get("response_text", "")
        assert result.get("model_used") != "fast-path", (
            f"a specific real question must not be hijacked by the generic builtin-KB "
            f"fast-path, got model_used={result.get('model_used')!r}, answer: {answer}"
        )
        assert "tailscale" in answer.lower(), f"the real answer from the uploaded document must be used, got: {answer}"


        # Guard against over-correcting: a genuinely short, definition-seeking query
        # for an UNAMBIGUOUS acronym (not on the short-ambiguous-acronym exclusion
        # list "vpn" was deliberately added to, alongside "it"/"ai"/"os" etc. — those
        # stay LLM-routed even when short, a pre-existing, intentional trade-off
        # favoring accuracy over instant speed for genuinely ambiguous short words)
        # must still get the instant builtin answer under the new length gate.
        result2 = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="new_user", session_id="builtin-kb-shortquery-session",
            user_query="What is SQL?",
        )
        assert result2.get("model_used") == "fast-path", "a short, unambiguous definition request should still use the fast path"
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM document_chunks WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM embeddings WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
            await session.commit()
