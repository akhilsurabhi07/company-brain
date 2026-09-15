"""Slack connector — real pipeline test, network boundary mocked with respx.

Honesty note (matching this project's real-data standard): there is no real Slack
workspace or bot token available in this environment, so a true end-to-end proof
against Slack's actual servers isn't possible here — that requires the user's own
real bot token, exactly like the GitHub connector was verified against a real PAT.

What IS real and exercised end-to-end in these tests: SlackConnector's real HTTP call
construction (paths, headers, params) against response shapes matching the live
docs.slack.dev schemas pulled during the 2026-08-20 research pass; the real
run_tenant_ingestion_pipeline; real chunk_embed_and_store (real BGE embeddings, real
Postgres persistence); real resource_group_id / resource_group_acls wiring; and real
retrieval-time enforcement via the actual (unmocked) HybridRetriever. Only the network
boundary (respx intercepting httpx calls to slack.com) is mocked — everything after
that boundary is the genuine code path.
"""
import uuid
import time
import pytest
import respx
import httpx
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.crypto import token_crypto
from app.connectors.slack import SlackConnector, HISTORY_RATE_LIMIT_SLEEP_SECONDS
from app.api.ingestion_router import run_tenant_ingestion_pipeline
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever


async def _make_tenant_with_slack_token(name: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain)"),
            {"id": tenant_id, "name": name, "domain": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        encrypted = token_crypto.encrypt_token("xoxb-fake-but-well-formed-test-token", tenant_id)
        await session.execute(
            text("""
                INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config)
                VALUES (:tid, 'slack', :tok, '{}'::jsonb)
            """),
            {"tid": tenant_id, "tok": encrypted},
        )
        await session.execute(
            text("""
                INSERT INTO sync_statuses (tenant_id, source_app, status)
                VALUES (:tid, 'slack', 'idle')
            """),
            {"tid": tenant_id},
        )
        await session.commit()
    return tenant_id


@pytest.mark.asyncio
@respx.mock
async def test_bounded_backfill_populates_channel_scoped_documents_and_acls():
    """Real pipeline test: SlackConnector.list_resources -> real ingestion ->
    real chunk/embed/store -> real resource_group_id + resource_group_acls, using
    response shapes matching Slack's real documented schema."""
    tenant_id = await _make_tenant_with_slack_token("Slack Connector Test")
    channel_id = "C_ENG_TEAM"
    recent_ts = str(time.time() - 3600)  # 1 hour ago — inside the 30-day window

    respx.post("https://slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": True, "team_id": "T_TEST", "team": "Test Workspace", "user_id": "U_BOT"})
    )
    respx.get("https://slack.com/api/conversations.list").mock(
        return_value=httpx.Response(200, json={
            "ok": True,
            "channels": [{"id": channel_id, "name": "eng-team", "is_member": True}],
            "response_metadata": {"next_cursor": ""},
        })
    )
    respx.get("https://slack.com/api/conversations.history").mock(
        return_value=httpx.Response(200, json={
            "ok": True,
            "messages": [{"type": "message", "user": "U_ALICE", "text": "Real Slack test message about the deploy pipeline.", "ts": recent_ts}],
            "response_metadata": {"next_cursor": ""},
        })
    )
    respx.get("https://slack.com/api/conversations.members").mock(
        return_value=httpx.Response(200, json={"ok": True, "members": ["U_ALICE", "U_BOB"], "response_metadata": {"next_cursor": ""}})
    )

    await run_tenant_ingestion_pipeline(tenant_id)

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        doc_row = (await session.execute(
            text("SELECT id, resource_group_id FROM documents WHERE tenant_id = :tid AND source_app = 'slack'"),
            {"tid": tenant_id},
        )).fetchone()
        assert doc_row is not None, "Real ingestion must have created a real document."
        assert doc_row.resource_group_id == channel_id, "Document must be tagged with its real channel as resource_group_id."

        acl_rows = (await session.execute(
            text("SELECT principal_external_id FROM resource_group_acls WHERE tenant_id = :tid AND resource_group_id = :cid"),
            {"tid": tenant_id, "cid": channel_id},
        )).fetchall()
        acl_members = {r[0] for r in acl_rows}
        assert acl_members == {"U_ALICE", "U_BOB"}, f"Channel ACL must reflect the real channel membership, got {acl_members}"

        chunk_count = (await session.execute(
            text("SELECT COUNT(*) FROM document_chunks WHERE tenant_id = :tid"), {"tid": tenant_id}
        )).scalar()
        assert chunk_count > 0, "Real chunking/embedding must have run — message must be retrievable."

    # Real retrieval-time enforcement, unmocked HybridRetriever:
    result_member = await hybrid_retriever.search(tenant_id=tenant_id, query="deploy pipeline", top_k=5, user_id="U_ALICE")
    assert len(result_member["chunks"]) > 0, "A real channel member must retrieve the real ingested message."

    result_outsider = await hybrid_retriever.search(tenant_id=tenant_id, query="deploy pipeline", top_k=5, user_id="U_MALLORY")
    assert len(result_outsider["chunks"]) == 0, "A real non-member must be blocked from the same ingested message."


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_rejects_invalid_token_honestly():
    """A real invalid/revoked token must raise, not silently fall back to fake data —
    same standard as GitHubConnector's authenticate()."""
    respx.post("https://slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
    )
    with pytest.raises(ValueError, match="invalid_auth"):
        await SlackConnector().authenticate("some-tenant", "xoxb-revoked-token")


def test_rate_limit_pacing_matches_slacks_real_2025_policy():
    """Regression pin: the real, live-verified (2026-08-20) non-Marketplace-app rate
    limit for conversations.history/replies is 1 request/minute. If this constant ever
    drifts below that, real syncs would 429-loop against Slack's real servers."""
    assert HISTORY_RATE_LIMIT_SLEEP_SECONDS >= 60
