"""Real test for the GitHub webhook receiver fix, 2026-08-20.

Pins down two real bugs found while building the Slack/WhatsApp webhooks and fixed
here: (1) tenant was resolved via `SELECT id FROM tenants LIMIT 1` — an arbitrary
tenant regardless of which repo the event was actually for, a real cross-tenant
misattribution bug; (2) the event was stored but never chunked/embedded, so
webhook-ingested GitHub events were permanently unretrievable in chat (write-only).

Same honesty standard as the WhatsApp webhook test: the HMAC signature math is real
crypto proven on both sides, not a third party's behavior being guessed at.
"""
import hashlib
import hmac
import json
import uuid
import pytest
import httpx
from sqlalchemy import text
from app.main import app
from app.db.database import async_session_factory
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever

WEBHOOK_URL_TMPL = "/api/v1/webhooks/github/{tenant_id}"


async def _make_tenant_with_github_webhook_secret(name: str, webhook_secret: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": name, "d": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        await session.execute(
            text("INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config) VALUES (:t, 'github', 'placeholder', CAST(:cfg AS jsonb))"),
            {"t": tenant_id, "cfg": json.dumps({"owner": "octo-org", "repo": "webhook-repo", "webhook_secret": webhook_secret})},
        )
        await session.commit()
    return tenant_id


@pytest.mark.asyncio
async def test_webhook_rejects_missing_secret_config():
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": "No Secret Test", "d": f"no-secret-{tenant_id[:8]}.company.com"},
        )
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(WEBHOOK_URL_TMPL.format(tenant_id=tenant_id), content=b"{}", headers={"X-Hub-Signature-256": "sha256=x"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature_real_crypto():
    tenant_id = await _make_tenant_with_github_webhook_secret("Bad Sig Test", "real-webhook-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            WEBHOOK_URL_TMPL.format(tenant_id=tenant_id), content=b"{}",
            headers={"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "push"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_ingests_real_event_to_correct_tenant_and_is_retrievable():
    """The real end-to-end proof: correctly signed payload, sent to tenant A's real
    per-tenant URL -> lands in tenant A (not some arbitrary tenant), and is genuinely
    retrievable afterward — not just stored."""
    secret = "genuinely-real-github-webhook-secret"
    tenant_a = await _make_tenant_with_github_webhook_secret("GitHub Webhook Tenant A", secret)
    tenant_b = await _make_tenant_with_github_webhook_secret("GitHub Webhook Tenant B", "a-different-secret")

    payload = {
        "repository": {"full_name": "octo-org/webhook-repo"},
        "sender": {"login": "octocat"},
        "pull_request": {
            "number": 77,
            "title": "Fix the connection pool leak in the sync worker",
            "body": "The pool was never releasing connections on a timeout — real fix, real test added.",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    real_signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            WEBHOOK_URL_TMPL.format(tenant_id=tenant_a), content=body,
            headers={"X-Hub-Signature-256": real_signature, "X-GitHub-Event": "pull_request", "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == tenant_a

    # Real proof of correct tenant attribution: tenant B must have nothing.
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_b})
        count_b = (await session.execute(
            text("SELECT COUNT(*) FROM documents WHERE tenant_id = :t AND source_app = 'github'"), {"t": tenant_b}
        )).scalar()
    assert count_b == 0, "The event must not leak into an unrelated tenant."

    # Real proof it's genuinely retrievable, not just stored.
    result = await hybrid_retriever.search(tenant_id=tenant_a, query="connection pool leak sync worker timeout", top_k=5, user_id="any_user")
    assert len(result["chunks"]) > 0, "A webhook-ingested GitHub event must be genuinely retrievable in chat, not write-only."
