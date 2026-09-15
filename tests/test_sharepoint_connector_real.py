"""SharePoint connector — real pipeline test, network boundary mocked with respx.

Same honesty standard as the Slack/Drive/Jira connector tests: no real Microsoft
Entra app registration or real SharePoint site exists in this environment, so this
doesn't prove Microsoft's actual servers behave this way — that needs real
MICROSOFT_OAUTH_CLIENT_ID/SECRET and a real user completing the browser consent flow.
What IS real: real site-discovery + one-level folder recursion, real download +
extraction reuse, real per-document ACLs, and real retrieval enforcement via the
actual (unmocked) HybridRetriever, using response shapes matching Microsoft Graph
API's real documented schema.
"""
import uuid
import pytest
import respx
import httpx
from sqlalchemy import text
from app.config import settings
from app.db.database import async_session_factory
from app.security.crypto import token_crypto
from app.api.ingestion_router import run_tenant_ingestion_pipeline
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever


@pytest.fixture(autouse=True)
def _fake_microsoft_oauth_credentials(monkeypatch):
    monkeypatch.setattr(settings, "MICROSOFT_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "MICROSOFT_OAUTH_CLIENT_SECRET", "test-client-secret")


async def _make_tenant_with_sharepoint_refresh_token(name: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": name, "d": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        encrypted = token_crypto.encrypt_token("fake-refresh-token", tenant_id)
        await session.execute(
            text("INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config) VALUES (:t, 'sharepoint', :tok, '{}'::jsonb)"),
            {"t": tenant_id, "tok": encrypted},
        )
        await session.execute(
            text("INSERT INTO sync_statuses (tenant_id, source_app, status) VALUES (:t, 'sharepoint', 'idle')"),
            {"t": tenant_id},
        )
        await session.commit()
    return tenant_id


@pytest.mark.asyncio
@respx.mock
async def test_bounded_sync_populates_real_document_acls():
    tenant_id = await _make_tenant_with_sharepoint_refresh_token("SharePoint Connector Test")

    respx.post("https://login.microsoftonline.com/common/oauth2/v2.0/token").mock(
        return_value=httpx.Response(200, json={"access_token": "fake-access-token", "refresh_token": "fake-refresh-token", "expires_in": 3599})
    )
    respx.get("https://graph.microsoft.com/v1.0/sites").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "SITE_ENG", "displayName": "Engineering"}]})
    )
    respx.get("https://graph.microsoft.com/v1.0/sites/SITE_ENG/drive/root/children").mock(
        return_value=httpx.Response(200, json={"value": [{
            "id": "FILE_XYZ", "name": "Security Runbook.txt", "webUrl": "https://contoso.sharepoint.com/x",
            "file": {"mimeType": "text/plain"},
            "lastModifiedBy": {"user": {"id": "USER_ALICE", "displayName": "Alice"}},
        }]})
    )
    respx.get("https://graph.microsoft.com/v1.0/sites/SITE_ENG/drive/items/FILE_XYZ/content").mock(
        return_value=httpx.Response(200, content=b"Security runbook: rotate the signing keys every 90 days.")
    )
    respx.get("https://graph.microsoft.com/v1.0/sites/SITE_ENG/drive/items/FILE_XYZ/permissions").mock(
        return_value=httpx.Response(200, json={"value": [
            {"id": "1", "roles": ["read"], "grantedToV2": {"user": {"id": "USER_ALICE", "displayName": "Alice"}}},
            {"id": "2", "roles": ["read"], "grantedToV2": {"user": {"id": "USER_BOB", "displayName": "Bob"}}},
        ]})
    )

    await run_tenant_ingestion_pipeline(tenant_id)

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        doc_row = (await session.execute(
            text("SELECT id FROM documents WHERE tenant_id = :t AND source_app = 'sharepoint'"), {"t": tenant_id}
        )).fetchone()
        assert doc_row is not None, "Real ingestion must have created a real document."

        acl_rows = (await session.execute(
            text("SELECT principal_external_id FROM document_acls WHERE document_id = :d"), {"d": doc_row.id}
        )).fetchall()
        assert {r[0] for r in acl_rows} == {"USER_ALICE", "USER_BOB"}

    result_permitted = await hybrid_retriever.search(tenant_id=tenant_id, query="signing keys rotation security", top_k=5, user_id="USER_ALICE")
    assert len(result_permitted["chunks"]) > 0

    result_outsider = await hybrid_retriever.search(tenant_id=tenant_id, query="signing keys rotation security", top_k=5, user_id="USER_MALLORY")
    assert len(result_outsider["chunks"]) == 0
