"""
CRITICAL real bug found via live testing 2026-08-21: the conversation cache key
was built only from (query text, knowledge version, prompt version, persona,
tenant, provider) — caller_role was never part of it. The RBAC/ABAC content
filter redacts restricted facts (salary/payroll/compensation/bonus) BEFORE
generation, but the cache stores the final generated ANSWER — so once an admin
asked a salary question and got the real figure, that exact answer was cached
under a role-blind key. A member asking the identical question afterward hit
that same cache entry and received the admin's real, unredacted answer
verbatim — a complete bypass of the RBAC content filter via cache.

Confirmed live end-to-end: admin asked "What is the exact base salary figure
for senior engineers per annum?", got "...set at 18 lakhs per annum." A member
then asked the identical question and received cache_hit=true with the exact
same real figure.

Fixed by folding caller_role into the hashed cache key input, so admin and
non-admin traffic can never share a cache entry.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.processors.semantic_chunker import SemanticChunker
from app.embeddings.bge_embedder import bge_embedder
from app.db.chunk_vector_repo import chunk_vector_repo
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "77777777-7777-7777-7777-777777777777"


@pytest.mark.asyncio
async def test_admins_cached_answer_never_serves_a_members_identical_question():
    doc_id = str(uuid.uuid4())
    content = "Compensation Note: the base salary for Senior Engineers at this company is set at 21 lakhs per annum, with a 12% annual bonus."

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Cache Role Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"cacheroletest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :tid, 'upload', 'hr', 'doc', :ext, 'Compensation Note.pdf', :content, 'b', :s3key, 4)
            """),
            {"id": doc_id, "tid": TEST_TENANT, "ext": f"cacheroletest-{doc_id[:8]}", "s3key": f"cacheroletest-{doc_id[:8]}", "content": content},
        )
        await session.commit()

    chunks = SemanticChunker().chunk_document(tenant_id=TEST_TENANT, document_id=doc_id, full_text=content, resource_category="hr")
    embeddings = bge_embedder.embed_texts([c.text_content for c in chunks])
    await chunk_vector_repo.save_chunks_and_embeddings(tenant_id=TEST_TENANT, document_id=doc_id, chunks=chunks, embeddings=embeddings)

    try:
        service = ConversationService()
        query = "What is the exact base salary figure for senior engineers per annum?"

        admin_result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="admin_user", session_id="cache-role-admin-session",
            user_query=query, caller_role="admin",
        )
        # Real providers (observed live from Groq here) sometimes typeset a
        # narrow no-break space (U+202F) between a number and its unit
        # instead of a plain ASCII space — real typographic formatting, not
        # a missing fact. Same normalization already applied elsewhere this
        # session (test_upload_pipeline_real.py, test_rbac_content_filtering_real.py).
        import re as _re
        admin_answer = _re.sub(r"\s+", " ", admin_result.get("response_text", "").lower())
        assert "21 lakh" in admin_answer, f"admin should see the real figure, got: {admin_answer}"

        member_result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="member_user", session_id="cache-role-member-session",
            user_query=query, caller_role="member",
        )
        member_answer = _re.sub(r"\s+", " ", member_result.get("response_text", "").lower())
        assert "21 lakh" not in member_answer, (
            f"CRITICAL: member received the admin's cached, unredacted answer — "
            f"RBAC content filter bypassed via cache. Got: {member_answer}"
        )
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM document_chunks WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM embeddings WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
            await session.commit()
