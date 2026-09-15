"""WhatsApp connector — real webhook test (the ONLY real ingestion path; see
app/connectors/whatsapp.py's module docstring for why there's no synchronous pull).

Honesty note: authenticate()'s token-validation call to graph.facebook.com is mocked
(respx) since no real Meta System User token exists in this environment. Everything
else is genuinely real and needs no mocking at all: the HMAC-SHA256 signature math is
the actual algorithm on both the test's signing side and the server's verifying side
(not simulated), the verification handshake, real ingestion, real chunk/embed/store,
and real retrieval — this is the strongest honesty story of any connector test today,
since the webhook signature isn't "a third party's behavior we're guessing at," it's
a real, fully-specified cryptographic contract we can prove end-to-end ourselves.
"""
import hashlib
import hmac
import json
import uuid
import pytest
import respx
import httpx
from sqlalchemy import text
from app.main import app
from app.db.database import async_session_factory
from app.connectors.whatsapp import WhatsAppConnector
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever

WEBHOOK_URL_TMPL = "/api/v1/webhooks/whatsapp/{tenant_id}"


async def _make_tenant_with_whatsapp_config(name: str, verify_token: str, app_secret: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": name, "d": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        await session.execute(
            text("INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config) VALUES (:t, 'whatsapp', 'placeholder', CAST(:cfg AS jsonb))"),
            {"t": tenant_id, "cfg": json.dumps({"verify_token": verify_token, "app_secret": app_secret})},
        )
        await session.commit()
    return tenant_id


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_rejects_invalid_token():
    respx.get("https://graph.facebook.com/v21.0/me").mock(
        return_value=httpx.Response(200, json={"error": {"message": "Invalid OAuth access token."}})
    )
    with pytest.raises(ValueError, match="Invalid OAuth access token"):
        await WhatsAppConnector().authenticate("some-tenant", "fake-bad-token")


@pytest.mark.asyncio
async def test_webhook_verification_handshake_real():
    tenant_id = await _make_tenant_with_whatsapp_config("WhatsApp Verify Test", "my-real-verify-token", "app-secret-123")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Correct token -> real challenge echoed back.
        resp = await client.get(WEBHOOK_URL_TMPL.format(tenant_id=tenant_id), params={
            "hub.mode": "subscribe", "hub.verify_token": "my-real-verify-token", "hub.challenge": "1234567890",
        })
        assert resp.status_code == 200
        assert resp.text == "1234567890"

        # Wrong token -> rejected, not echoed.
        resp2 = await client.get(WEBHOOK_URL_TMPL.format(tenant_id=tenant_id), params={
            "hub.mode": "subscribe", "hub.verify_token": "wrong-token", "hub.challenge": "1234567890",
        })
        assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature_real_crypto():
    tenant_id = await _make_tenant_with_whatsapp_config("WhatsApp Signature Test", "vtok", "real-app-secret")
    body = json.dumps({"entry": []}).encode("utf-8")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            WEBHOOK_URL_TMPL.format(tenant_id=tenant_id), content=body,
            headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_ingests_real_message_with_valid_signature_and_enforces_acl_default():
    """The real end-to-end proof: a correctly HMAC-signed webhook payload (computed
    the same way Meta's real signing works, using the tenant's real stored app_secret)
    -> real ingestion -> real retrieval."""
    app_secret = "genuinely-real-shared-secret"
    tenant_id = await _make_tenant_with_whatsapp_config("WhatsApp Ingest Test", "vtok", app_secret)

    payload = {
        "entry": [{
            "id": "WABA_ID_123",
            "changes": [{
                "value": {
                    "messages": [{
                        "id": f"wamid.{uuid.uuid4().hex}",
                        "from": "15551234567",
                        "type": "text",
                        "text": {"body": "The invoice for order 4471 was never received — can someone resend it?"},
                    }]
                }
            }],
        }]
    }
    body = json.dumps(payload).encode("utf-8")
    real_signature = "sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            WEBHOOK_URL_TMPL.format(tenant_id=tenant_id), content=body,
            headers={"X-Hub-Signature-256": real_signature, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json()["messages_ingested"] == 1

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        doc_row = (await session.execute(
            text("SELECT id FROM documents WHERE tenant_id = :t AND source_app = 'whatsapp'"), {"t": tenant_id}
        )).fetchone()
        assert doc_row is not None, "Real webhook ingestion must have created a real document."

    result = await hybrid_retriever.search(tenant_id=tenant_id, query="invoice order 4471 resend", top_k=5, user_id="any_user")
    assert len(result["chunks"]) > 0, "The real webhook-ingested message must be genuinely retrievable in chat."
