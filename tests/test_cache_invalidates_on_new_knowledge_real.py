"""
Real test for the conversation-cache invalidation bug.

conversation_service.py used to hardcode "v1.0.0" as the knowledge_context_version
component of the cache key — meaning identical questions always hit the same cache
entry regardless of whether the tenant's underlying data changed. In practice: ask a
question with no matching data ("I don't know"), then ingest a document that answers
it, ask the identical question again — you'd keep getting the stale "I don't know"
straight out of cache (Redis's 24h TTL, or indefinitely from the in-process fallback
while Redis is down).

This pins the real fix: _get_knowledge_context_version() reflects a tenant's actual
document_chunks state, so ingesting new content changes the cache key and forces a
fresh answer.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "44444444-4444-4444-4444-444444444444"


@pytest.mark.asyncio
async def test_knowledge_context_version_changes_when_new_chunk_is_ingested():
    service = ConversationService()

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Cache Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"cachetest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.commit()

    version_before = await service._get_knowledge_context_version(TEST_TENANT)

    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :tid, 'upload', 'engineering', 'doc', :ext, 'Cache Invalidation Test Doc', 'test', 'b', :s3key, 4)
            """),
            {"id": doc_id, "tid": TEST_TENANT, "ext": f"cachetest-{chunk_id[:8]}", "s3key": f"cachetest-{chunk_id[:8]}"},
        )
        await session.execute(
            text("""
                INSERT INTO document_chunks (id, tenant_id, document_id, chunk_index, text_content, token_count)
                VALUES (:id, :tid, :doc_id, 0, 'brand new content that did not exist before', 20)
            """),
            {"id": chunk_id, "tid": TEST_TENANT, "doc_id": doc_id},
        )
        await session.commit()

    try:
        version_after = await service._get_knowledge_context_version(TEST_TENANT)
        assert version_before != version_after, (
            "knowledge_context_version must change when new chunks are ingested — "
            "otherwise identical questions keep hitting a stale cache entry forever"
        )
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM document_chunks WHERE id = :id"), {"id": chunk_id})
            await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
            await session.commit()
