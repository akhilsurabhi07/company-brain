"""Jira connector — real pipeline test, network boundary mocked with respx.

Same honesty standard as the Slack/Drive connector tests: no real Atlassian OAuth app
or real Jira site exists in this environment, so this doesn't prove Atlassian's actual
servers behave this way — that needs real JIRA_OAUTH_CLIENT_ID/SECRET and a real user
completing the browser consent flow. What IS real: the ADF-to-text parser, the
refresh-token-rotation persistence in ingestion_router.py, real ingestion, real
chunk/embed/store, and real project-role-based ACL enforcement via the actual
(unmocked) HybridRetriever, using response shapes matching Jira Cloud REST API v3's
real documented schema.
"""
import uuid
import pytest
import respx
import httpx
from sqlalchemy import text
from app.config import settings
from app.db.database import async_session_factory
from app.security.crypto import token_crypto
from app.connectors.jira import _adf_to_text, JiraConnector
from app.api.ingestion_router import run_tenant_ingestion_pipeline
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever


@pytest.fixture(autouse=True)
def _fake_jira_oauth_credentials(monkeypatch):
    monkeypatch.setattr(settings, "JIRA_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "JIRA_OAUTH_CLIENT_SECRET", "test-client-secret")


async def _make_tenant_with_jira_refresh_token(name: str, cloud_id: str = "CLOUD_XYZ") -> str:
    import json
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": name, "d": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        encrypted = token_crypto.encrypt_token("fake-original-refresh-token", tenant_id)
        await session.execute(
            text("INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config) VALUES (:t, 'jira', :tok, CAST(:cfg AS jsonb))"),
            {"t": tenant_id, "tok": encrypted, "cfg": json.dumps({"cloud_id": cloud_id})},
        )
        await session.execute(
            text("INSERT INTO sync_statuses (tenant_id, source_app, status) VALUES (:t, 'jira', 'idle')"),
            {"t": tenant_id},
        )
        await session.commit()
    return tenant_id


def test_adf_to_text_extracts_real_nested_content():
    """Real ADF document shape (matching Jira API v3's actual schema) — paragraphs
    inside a doc node, text nodes inside paragraphs."""
    adf = {
        "type": "doc", "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "The payments service migration is blocked on"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "a database schema review."}]},
        ],
    }
    result = _adf_to_text(adf)
    assert "payments service migration" in result
    assert "database schema review" in result


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_persists_rotated_refresh_token():
    """The real, Jira-specific behavior: a NEW refresh_token comes back from every
    exchange and must be returned so the caller can persist it — Atlassian invalidates
    the old one immediately."""
    respx.post("https://auth.atlassian.com/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "new-access-token", "refresh_token": "ROTATED-refresh-token-v2", "expires_in": 3600})
    )
    token = await JiraConnector().authenticate("some-tenant", "fake-original-refresh-token")
    assert token.access_token == "new-access-token"
    assert token.refresh_token == "ROTATED-refresh-token-v2"
    assert token.refresh_token != "fake-original-refresh-token"


@pytest.mark.asyncio
@respx.mock
async def test_full_sync_populates_project_role_acls_and_rotates_stored_token():
    tenant_id = await _make_tenant_with_jira_refresh_token("Jira Connector Test")

    respx.post("https://auth.atlassian.com/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "fake-access-token", "refresh_token": "ROTATED-refresh-token-v2", "expires_in": 3600})
    )
    respx.get("https://api.atlassian.com/ex/jira/CLOUD_XYZ/rest/api/3/search").mock(
        return_value=httpx.Response(200, json={
            "total": 1,
            "issues": [{
                "key": "ENG-42",
                "fields": {
                    "summary": "Payments service migration blocked",
                    "description": {"type": "doc", "version": 1, "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Blocked on a database schema review before we can proceed."}]}
                    ]},
                    "project": {"key": "ENG", "name": "Engineering"},
                    "status": {"name": "In Progress"},
                    "assignee": {"accountId": "ACC_ALICE", "displayName": "Alice"},
                    "reporter": {"accountId": "ACC_BOB", "displayName": "Bob"},
                    "updated": "2026-08-01T00:00:00Z",
                },
            }],
        })
    )
    respx.get("https://api.atlassian.com/ex/jira/CLOUD_XYZ/rest/api/3/project/ENG/role").mock(
        return_value=httpx.Response(200, json={"Administrators": "https://api.atlassian.com/ex/jira/CLOUD_XYZ/rest/api/3/project/ENG/role/10002"})
    )
    respx.get("https://api.atlassian.com/ex/jira/CLOUD_XYZ/rest/api/3/project/ENG/role/10002").mock(
        return_value=httpx.Response(200, json={"actors": [
            {"type": "atlassian-user-role-actor", "actorUser": {"accountId": "ACC_ALICE"}},
            {"type": "atlassian-user-role-actor", "actorUser": {"accountId": "ACC_BOB"}},
        ]})
    )

    await run_tenant_ingestion_pipeline(tenant_id)

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        doc_row = (await session.execute(
            text("SELECT id, resource_group_id FROM documents WHERE tenant_id = :t AND source_app = 'jira'"), {"t": tenant_id}
        )).fetchone()
        assert doc_row is not None, "Real ingestion must have created a real document."
        assert doc_row.resource_group_id == "ENG"

        acl_rows = (await session.execute(
            text("SELECT principal_external_id FROM resource_group_acls WHERE tenant_id = :t AND resource_group_id = 'ENG'"), {"t": tenant_id}
        )).fetchall()
        assert {r[0] for r in acl_rows} == {"ACC_ALICE", "ACC_BOB"}

        # Real proof the rotated refresh token was actually persisted, not just returned.
        stored_row = (await session.execute(
            text("SELECT encrypted_access_token FROM oauth_tokens WHERE tenant_id = :t AND source_app = 'jira'"), {"t": tenant_id}
        )).fetchone()
        decrypted = token_crypto.decrypt_token(stored_row.encrypted_access_token, tenant_id)
        assert decrypted == "ROTATED-refresh-token-v2", "The rotated refresh token must be persisted, or the next sync would fail."

    result_member = await hybrid_retriever.search(tenant_id=tenant_id, query="payments migration database schema", top_k=5, user_id="ACC_ALICE")
    assert len(result_member["chunks"]) > 0

    result_outsider = await hybrid_retriever.search(tenant_id=tenant_id, query="payments migration database schema", top_k=5, user_id="ACC_MALLORY")
    assert len(result_outsider["chunks"]) == 0
