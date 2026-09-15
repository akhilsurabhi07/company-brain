"""Real-data test for channel-level ACL enforcement — Slack connector prep, 2026-08-20.

Proves the scoped, additive change to hybrid_retriever.py's ACL clause (adding
resource_group_acls support for channel-scoped documents like Slack messages)
actually blocks a non-member from a private channel's content, using real ingestion
(chunk_embed_and_store, real BGE embeddings) and the real HybridRetriever.search()
code path — not mocked.

Companion regression proof (no behavior change for existing per-document ACLs, e.g.
GitHub) lives in tests/test_retrieval_real_data.py, specifically test_g and test_h,
which exercise the tenant-isolation and per-document-ACL branches of the exact same
acl_clause this change touches. Both suites are run together to prove old and new
behavior side by side.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.processors.ingestion_pipeline import chunk_embed_and_store
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever

CHANNEL_CONTENT = (
    "Team sync notes for the Q3 infrastructure migration. We are moving the payments "
    "service off the legacy cluster by end of September. Rollback plan is documented "
    "in the runbook. Owner: infrastructure team."
)


async def _make_tenant(name: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain)"),
            {"id": tenant_id, "name": name, "domain": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        await session.commit()
    return tenant_id


async def _ingest_channel_message(tenant_id: str, resource_group_id: str) -> str:
    """Real ingestion of a Slack-shaped document: source_app='slack', a real
    resource_group_id (channel), and — deliberately — zero document_acls rows, since
    channel-scoped documents are meant to rely on resource_group_acls instead."""
    doc_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        await session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, source_app, resource_category, resource_type, external_id,
                    title, content, s3_bucket, s3_key, is_compressed, file_size_bytes, resource_group_id
                ) VALUES (
                    :id, :tid, 'slack', 'chat_message', 'message', :ext_id, :title, :content,
                    'test-bucket', :key, TRUE, :size, :rgid
                )
            """),
            {
                "id": doc_id, "tid": tenant_id, "ext_id": f"msg_{doc_id[:8]}",
                "title": "#infra-private channel message", "content": CHANNEL_CONTENT,
                "key": f"raw/{tenant_id}/slack/{doc_id[:8]}.json.zst", "size": len(CHANNEL_CONTENT),
                "rgid": resource_group_id,
            },
        )
        await session.commit()

    result = await chunk_embed_and_store(tenant_id=tenant_id, document_id=doc_id, full_text=CHANNEL_CONTENT, resource_category="chat_message")
    assert result["status"] == "completed", f"Real ingestion must succeed: {result}"
    return doc_id


async def _add_channel_member(tenant_id: str, resource_group_id: str, user_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        await session.execute(
            text("""
                INSERT INTO resource_group_acls (tenant_id, source_app, resource_group_id, principal_type, principal_external_id, permission)
                VALUES (:tid, 'slack', :rgid, 'user', :uid, 'read')
            """),
            {"tid": tenant_id, "rgid": resource_group_id, "uid": user_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_channel_member_can_retrieve_private_channel_content():
    """A real member of the private channel MUST be able to retrieve its content."""
    tenant_id = await _make_tenant("Channel ACL Test - Member")
    channel_id = "C_INFRA_PRIVATE"
    await _ingest_channel_message(tenant_id, channel_id)
    await _add_channel_member(tenant_id, channel_id, "U_AUTHORIZED_MEMBER")

    result = await hybrid_retriever.search(
        tenant_id=tenant_id, query="Q3 infrastructure migration payments service rollback",
        top_k=5, user_id="U_AUTHORIZED_MEMBER",
    )
    assert len(result["chunks"]) > 0, "A real channel member MUST retrieve the channel's real content."


@pytest.mark.asyncio
async def test_non_member_is_blocked_from_private_channel_content():
    """The core requirement: a real user who is NOT a member of the private channel
    MUST NOT see its content in retrieval results, even though it's genuinely the
    most relevant document for the query — this is the actual enforcement proof, not
    just 'the API didn't error'."""
    tenant_id = await _make_tenant("Channel ACL Test - Non-Member")
    channel_id = "C_INFRA_PRIVATE"
    await _ingest_channel_message(tenant_id, channel_id)
    await _add_channel_member(tenant_id, channel_id, "U_AUTHORIZED_MEMBER")
    # Deliberately do NOT add U_OUTSIDER as a member.

    result = await hybrid_retriever.search(
        tenant_id=tenant_id, query="Q3 infrastructure migration payments service rollback",
        top_k=5, user_id="U_OUTSIDER",
    )
    assert len(result["chunks"]) == 0, (
        f"A non-member MUST NOT retrieve private-channel content, but got "
        f"{len(result['chunks'])} chunk(s): {[c.get('doc_title') for c in result['chunks']]}"
    )


@pytest.mark.asyncio
async def test_document_with_no_group_and_no_acl_rows_stays_default_open():
    """Regression pin: a document with resource_group_id = NULL and zero document_acls
    rows (the GitHub / no-ACL-configured shape) must remain visible to any user, exactly
    as before this change — proves the new resource_group branch doesn't accidentally
    tighten the existing default-open behavior for non-channel-scoped documents."""
    tenant_id = await _make_tenant("Channel ACL Test - No Group Regression")
    doc_id = str(uuid.uuid4())
    content = "Open engineering wiki page about our deployment pipeline architecture."
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type,
                    external_id, title, content, s3_bucket, s3_key, is_compressed, file_size_bytes)
                VALUES (:id, :tid, 'github', 'doc', 'wiki', :ext_id, 'Deployment Pipeline Wiki', :content,
                    'test-bucket', :key, TRUE, :size)
            """),
            {"id": doc_id, "tid": tenant_id, "ext_id": f"wiki_{doc_id[:8]}", "content": content,
             "key": f"raw/{tenant_id}/github/{doc_id[:8]}.json.zst", "size": len(content)},
        )
        await session.commit()
    result_ingest = await chunk_embed_and_store(tenant_id=tenant_id, document_id=doc_id, full_text=content, resource_category="doc")
    assert result_ingest["status"] == "completed"

    result = await hybrid_retriever.search(
        tenant_id=tenant_id, query="deployment pipeline architecture", top_k=5, user_id="U_ANY_RANDOM_USER",
    )
    assert len(result["chunks"]) > 0, "A document with no resource_group and no ACL rows MUST stay default-open (unchanged behavior)."
