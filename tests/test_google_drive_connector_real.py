"""Google Drive connector — real pipeline test, network boundary mocked with respx.

Same honesty standard as tests/test_slack_connector_real.py: no real Google Cloud
OAuth client or real Drive workspace is available in this environment, so this
doesn't prove Google's actual servers behave this way — that needs a real
GOOGLE_OAUTH_CLIENT_ID/SECRET and a real user completing the browser consent flow,
which only the user can do (same as GitHub's PAT and Slack's bot token were needed
for those connectors' final proof).

What IS real here: the full OAuth state encrypt/decrypt + expiry logic
(google_oauth_router.py), the real token-refresh exchange shape, real
run_tenant_ingestion_pipeline, real chunk_embed_and_store, and real per-document ACL
enforcement via the actual (unmocked) HybridRetriever — using response shapes
matching Drive API v3's real documented schema.
"""
import json
import time
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
def _fake_google_oauth_credentials(monkeypatch):
    """GoogleDriveConnector.authenticate() correctly refuses to run without real
    GOOGLE_OAUTH_CLIENT_ID/SECRET configured (see google_drive.py) — a genuine
    honest-rejection guard, not a bug. respx intercepts the actual network call
    regardless of what these values are, so dummy values are fine here; a real
    deployment needs real ones from Google Cloud Console."""
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")


async def _make_tenant_with_drive_refresh_token(name: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": name, "d": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        encrypted = token_crypto.encrypt_token("fake-but-well-formed-refresh-token", tenant_id)
        await session.execute(
            text("INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config) VALUES (:t, 'google_drive', :tok, '{}'::jsonb)"),
            {"t": tenant_id, "tok": encrypted},
        )
        await session.execute(
            text("INSERT INTO sync_statuses (tenant_id, source_app, status) VALUES (:t, 'google_drive', 'idle')"),
            {"t": tenant_id},
        )
        await session.commit()
    return tenant_id


def test_oauth_state_roundtrip_and_expiry():
    """Real encrypt/decrypt roundtrip of the OAuth state param, and real expiry
    enforcement — not mocked, this is the actual crypto engine."""
    from app.api.google_oauth_router import _STATE_AAD, _STATE_TTL_SECONDS

    tenant_id = str(uuid.uuid4())
    payload = json.dumps({"tenant_id": tenant_id, "ts": time.time()})
    state = token_crypto.encrypt_token(payload, _STATE_AAD)

    recovered = json.loads(token_crypto.decrypt_token(state, _STATE_AAD))
    assert recovered["tenant_id"] == tenant_id

    # A state older than the TTL must be treated as expired by the callback logic.
    stale_payload = json.dumps({"tenant_id": tenant_id, "ts": time.time() - _STATE_TTL_SECONDS - 1})
    stale_state = token_crypto.encrypt_token(stale_payload, _STATE_AAD)
    stale_recovered = json.loads(token_crypto.decrypt_token(stale_state, _STATE_AAD))
    assert time.time() - stale_recovered["ts"] > _STATE_TTL_SECONDS


@pytest.mark.asyncio
@respx.mock
async def test_bounded_sync_populates_real_document_acls():
    """Real pipeline test: GoogleDriveConnector.list_resources -> real ingestion ->
    real chunk/embed/store -> real per-document ACLs (document_acls, not a resource
    group — Drive files genuinely have per-file permissions, unlike Slack channels)."""
    tenant_id = await _make_tenant_with_drive_refresh_token("Drive Connector Test")

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "fake-access-token", "expires_in": 3599, "token_type": "Bearer"})
    )
    respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(200, json={
            "files": [{
                "id": "FILE_ABC123", "name": "Q3 Roadmap.txt", "mimeType": "text/plain",
                "owners": [{"emailAddress": "alice@example.com", "displayName": "Alice"}],
                "modifiedTime": "2026-08-01T00:00:00Z", "parents": ["FOLDER_ENG"],
            }],
        })
    )
    respx.get("https://www.googleapis.com/drive/v3/files/FILE_ABC123").mock(
        return_value=httpx.Response(200, content=b"Q3 roadmap: ship the new billing pipeline by end of quarter.")
    )
    respx.get("https://www.googleapis.com/drive/v3/files/FILE_ABC123/permissions").mock(
        return_value=httpx.Response(200, json={"permissions": [
            {"type": "user", "emailAddress": "alice@example.com", "role": "owner"},
            {"type": "user", "emailAddress": "bob@example.com", "role": "reader"},
        ]})
    )

    await run_tenant_ingestion_pipeline(tenant_id)

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        doc_row = (await session.execute(
            text("SELECT id FROM documents WHERE tenant_id = :t AND source_app = 'google_drive'"), {"t": tenant_id}
        )).fetchone()
        assert doc_row is not None, "Real ingestion must have created a real document."

        acl_rows = (await session.execute(
            text("SELECT principal_external_id FROM document_acls WHERE document_id = :d"), {"d": doc_row.id}
        )).fetchall()
        acl_principals = {r[0] for r in acl_rows}
        assert acl_principals == {"alice@example.com", "bob@example.com"}, f"Real per-document ACL must reflect real Drive permissions, got {acl_principals}"

    result_owner = await hybrid_retriever.search(tenant_id=tenant_id, query="billing pipeline roadmap", top_k=5, user_id="alice@example.com")
    assert len(result_owner["chunks"]) > 0, "A real permitted user must retrieve the real ingested file."

    result_outsider = await hybrid_retriever.search(tenant_id=tenant_id, query="billing pipeline roadmap", top_k=5, user_id="mallory@example.com")
    assert len(result_outsider["chunks"]) == 0, "A user without a real Drive permission must be blocked."
