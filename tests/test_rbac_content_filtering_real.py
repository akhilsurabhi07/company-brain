"""
Real test for RBAC/ABAC content filtering, ported into the live retrieval path from
app/gateway/authorization/policy_engine.py — a real, tested Module 5 component that
existed but was never wired to live chat at all (see the gateway-orphaned-subsystem
memory). Before this, nothing in the live conversation pipeline filtered retrieved
chunk *content* by role — an "admin" and a "member" got identical answers even when
a chunk contained salary/payroll data.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.processors.semantic_chunker import SemanticChunker
from app.embeddings.bge_embedder import bge_embedder
from app.db.chunk_vector_repo import chunk_vector_repo
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "88888888-8888-8888-8888-888888888888"


@pytest.mark.asyncio
async def test_member_role_never_sees_salary_content_but_admin_does():
    doc_id = str(uuid.uuid4())
    content = "Q3 Payroll Update: Base salary for the engineering team was increased by 8% effective July, with an additional annual bonus pool."

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'RBAC Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"rbactest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :tid, 'upload', 'hr', 'doc', :ext, 'Q3 Payroll Update.pdf', :content, 'b', :s3key, 4)
            """),
            {"id": doc_id, "tid": TEST_TENANT, "ext": f"rbactest-{doc_id[:8]}", "s3key": f"rbactest-{doc_id[:8]}", "content": content},
        )
        await session.commit()

    chunks = SemanticChunker().chunk_document(tenant_id=TEST_TENANT, document_id=doc_id, full_text=content, resource_category="hr")
    embeddings = bge_embedder.embed_texts([c.text_content for c in chunks])
    await chunk_vector_repo.save_chunks_and_embeddings(tenant_id=TEST_TENANT, document_id=doc_id, chunks=chunks, embeddings=embeddings)

    try:
        service = ConversationService()

        admin_result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="admin_user", session_id="rbac-admin-session",
            user_query="what was the Q3 payroll update", caller_role="admin",
        )
        # Real flake found 2026-08-21: some providers (Groq's openai/gpt-oss-120b seen
        # live) typeset "8%" with a narrow no-break space (U+202F) between the number
        # and the percent sign, a real typographic-formatting choice, not a wrong or
        # missing fact — normalize whitespace before checking so the test tracks
        # whether the real fact is present, not exact byte-level spacing.
        admin_answer = admin_result.get("response_text", "").lower().replace(" ", "").replace(" ", "")
        assert "8%" in admin_answer or "salary" in admin_answer

        member_result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="member_user", session_id="rbac-member-session",
            user_query="what was the Q3 payroll update", caller_role="member",
        )
        member_answer = member_result.get("response_text", "").lower()
        # The real thing that must never leak: the specific filtered fact. The answer
        # may legitimately echo the word "payroll" back from the user's own question
        # text as part of an honest "I couldn't find that" refusal — that's not a leak.
        assert "8%" not in member_answer
        assert "increased" not in member_answer and "bonus pool" not in member_answer
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM document_chunks WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM embeddings WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
            await session.commit()


@pytest.mark.asyncio
async def test_member_still_gets_legitimate_fact_when_chunk_also_contains_restricted_content():
    """Real bug found via live testing 2026-08-21: the filter used to drop the ENTIRE
    chunk if it contained a restricted term anywhere, even alongside an unrelated,
    legitimate fact. A real document mixing leave-policy info with salary info in one
    chunk meant a member asking the plain "how many leave days" question got the whole
    chunk denied and fell through to a wrong, hallucinated world-knowledge answer
    instead of the correct real one. Fixed to redact only the restricted sentence(s),
    keeping the rest of the chunk's real content intact."""
    doc_id = str(uuid.uuid4())
    content = (
        "Engineering Leave Policy: all full-time engineers get 24 days of paid annual leave per year. "
        "Separately, the base salary for Senior Engineers is 18 lakhs per annum with a 15% bonus."
    )

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'RBAC Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"rbactest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :tid, 'upload', 'hr', 'doc', :ext, 'Leave & Compensation Policy.pdf', :content, 'b', :s3key, 4)
            """),
            {"id": doc_id, "tid": TEST_TENANT, "ext": f"rbactest-{doc_id[:8]}", "s3key": f"rbactest-{doc_id[:8]}", "content": content},
        )
        await session.commit()

    chunks = SemanticChunker().chunk_document(tenant_id=TEST_TENANT, document_id=doc_id, full_text=content, resource_category="hr")
    embeddings = bge_embedder.embed_texts([c.text_content for c in chunks])
    await chunk_vector_repo.save_chunks_and_embeddings(tenant_id=TEST_TENANT, document_id=doc_id, chunks=chunks, embeddings=embeddings)

    try:
        service = ConversationService()
        member_result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="member_user", session_id="rbac-mixed-member-session",
            user_query="how many days of annual leave do engineers get", caller_role="member",
        )
        member_answer = member_result.get("response_text", "").lower()
        assert "24" in member_answer, f"legitimate fact must survive redaction, got: {member_answer}"
        assert "18 lakh" not in member_answer and "15%" not in member_answer
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM document_chunks WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM embeddings WHERE document_id = :id"), {"id": doc_id})
            await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
            await session.commit()
