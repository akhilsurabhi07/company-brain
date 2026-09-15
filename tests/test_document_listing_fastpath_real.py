"""
Real test for the "what documents/files do you have" fast-path.

Found via live user testing 2026-08-21: a tenant with real ingested documents (a
GitHub PR, a Google Drive doc, a Jira ticket, a Slack message) still got a flat "I
don't have that information" for "what all the files you have about the company" —
because it's a meta/listing question, not a content question, so hybrid retrieval
(correctly, for what it's built to do) found no semantic match and fell through to
the honest-refusal path. Worse, the world-knowledge fallback then hallucinated a
fake generic table of "QuickBooks files" and "corporate filings" that had nothing to
do with this tenant's real data. This pins the real fix: such questions are routed to
an actual listing of the tenant's own documents table instead.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "55555555-5555-5555-5555-555555555555"


@pytest.mark.asyncio
async def test_document_listing_query_returns_real_documents_not_hallucination():
    doc_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Listing Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"listingtest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :tid, 'github', 'code', 'pr', :ext, 'PR #77: Real Test Fixture Document', 'test content', 'b', :s3key, 4)
            """),
            {"id": doc_id, "tid": TEST_TENANT, "ext": f"listingtest-{doc_id[:8]}", "s3key": f"listingtest-{doc_id[:8]}"},
        )
        await session.commit()

    try:
        service = ConversationService()
        # The exact real-world phrasing that broke the earlier fixed-phrase-list
        # version ("what all files" never matched "what all THE files you have").
        result = await service.process_turn(
            tenant_id=TEST_TENANT,
            user_id="test_user",
            session_id="listing-test-session",
            user_query="what all the files you have about the company",
        )
        assert result.get("model_used") == "fast-path"
        answer = result.get("response_text", "")
        assert "PR #77: Real Test Fixture Document" in answer
        # The real hallucination this fix replaced — must never reappear.
        assert "QuickBooks" not in answer
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
            await session.commit()


@pytest.mark.asyncio
async def test_document_listing_query_on_empty_tenant_is_honest_not_flat_refusal():
    empty_tenant = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": empty_tenant})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Empty Listing Co', :domain)"),
            {"id": empty_tenant, "domain": f"emptylisting-{empty_tenant[:8]}.example.com"},
        )
        await session.commit()

    service = ConversationService()
    result = await service.process_turn(
        tenant_id=empty_tenant,
        user_id="test_user",
        session_id="empty-listing-test-session",
        user_query="what documents do you have",
    )
    assert result.get("model_used") == "fast-path"
    assert "upload" in result.get("response_text", "").lower() or "connect" in result.get("response_text", "").lower()
