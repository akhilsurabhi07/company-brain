"""
Phase 2: Live GitHub Webhook Receiver
=======================================
Receives real-time GitHub webhook events (push, pull_request, issues, comments).
Verifies the payload signature using HMAC-SHA256.
Processes, compresses (Zstd), and stores each event in AWS S3 + PostgreSQL.
"""
import hashlib
import hmac
import json
import time
import uuid
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Header, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from app.db.database import async_session_factory
from app.storage.s3_storage import s3_storage
from app.processors.pii_redactor import pii_redactor

router = APIRouter(prefix="/api/v1/webhooks", tags=["Live Webhook Receivers"])


def verify_github_signature(webhook_secret: str, payload_bytes: bytes, signature_header: str) -> bool:
    """
    Verifies GitHub webhook payload using HMAC-SHA256 signature.
    GitHub sends: X-Hub-Signature-256: sha256=<hex_digest>
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_sig = "sha256=" + hmac.new(
        webhook_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_sig, signature_header)


@router.post("/github/{tenant_id}")
async def github_webhook(
    tenant_id: str,
    request: Request,
    x_hub_signature_256: str = Header(None),
    x_github_event: str = Header(None),
    x_github_delivery: str = Header(None),
):
    """
    Real-time GitHub Webhook Event Receiver — per-tenant URL (2026-08-20 fix; was a
    single shared /github endpoint with a hardcoded global secret and, worse, resolved
    tenant via `SELECT id FROM tenants LIMIT 1` — an arbitrary tenant, a real
    cross-tenant misattribution bug). Same reasoning as the Slack/WhatsApp webhooks:
    a per-tenant URL means the right secret (this tenant's real
    oauth_tokens.config.webhook_secret, set at /connect time same as owner/repo) is
    known before verification starts, and RLS is respected by setting tenant context
    from the URL first — no need to widen oauth_tokens' strict tenant-only RLS policy,
    which stays exactly as it was.
    Verifies HMAC signature → Redacts PII → Compresses → Uploads S3 → Indexes SQL →
    real chunk/embed/store, so a webhook-ingested event is genuinely retrievable
    (previously it was write-only — stored but never chunked or embedded).
    """
    payload_bytes = await request.body()

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("SELECT config FROM oauth_tokens WHERE tenant_id = :t AND source_app = 'github'"),
            {"t": tenant_id},
        )
        row = res.fetchone()

    webhook_secret = row[0].get("webhook_secret") if row and row[0] else None
    if not webhook_secret:
        raise HTTPException(status_code=404, detail="No GitHub webhook secret configured for this tenant.")

    if not verify_github_signature(webhook_secret, payload_bytes, x_hub_signature_256 or ""):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature. Unauthorized.")

    # Step 2: Parse the JSON payload
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event_type = x_github_event or "unknown"
    delivery_id = x_github_delivery or "no_delivery_id"

    # Step 3: Extract key fields from the event
    repo_name = payload.get("repository", {}).get("full_name", "unknown/repo")
    sender = payload.get("sender", {}).get("login", "unknown")
    resource_type = event_type
    resource_category = "code_event"

    # Determine a meaningful title per event type
    if event_type == "pull_request":
        pr = payload.get("pull_request", {})
        title = f"PR #{pr.get('number')}: {pr.get('title', '')}"
        external_id = f"gh_pr_{repo_name.replace('/', '_')}_{pr.get('number')}"
        resource_type = "pull_request"
        resource_category = "code_pr"
    elif event_type == "push":
        commits = payload.get("commits", [])
        branch = payload.get("ref", "").replace("refs/heads/", "")
        title = f"Push to {branch}: {len(commits)} commit(s) by {sender}"
        external_id = f"gh_push_{repo_name.replace('/', '_')}_{delivery_id}"
        resource_type = "push"
        resource_category = "code_event"
    elif event_type == "issues":
        issue = payload.get("issue", {})
        action = payload.get("action", "")
        title = f"Issue #{issue.get('number')} [{action}]: {issue.get('title', '')}"
        external_id = f"gh_issue_{repo_name.replace('/', '_')}_{issue.get('number')}_{action}"
        resource_type = "issue"
        resource_category = "code_issue"
    elif event_type == "issue_comment":
        issue = payload.get("issue", {})
        title = f"Comment on Issue #{issue.get('number')} by {sender}"
        external_id = f"gh_comment_{repo_name.replace('/', '_')}_{delivery_id}"
        resource_type = "issue_comment"
        resource_category = "code_event"
    else:
        title = f"GitHub Event: {event_type} on {repo_name}"
        external_id = f"gh_{event_type}_{delivery_id}"

    # Step 5: Redact secrets from payload
    clean_content = pii_redactor.redact_secrets(json.dumps(payload, indent=2))

    # Step 6: Compress + Upload raw payload to AWS S3
    s3_key, file_bytes_len = s3_storage.save_raw_json(
        tenant_id=tenant_id,
        source_app="github",
        resource_type=resource_type,
        external_id=external_id,
        raw_payload=payload,
        compress=True,
    )

    # Step 7: Index metadata in PostgreSQL — RETURNING id, same reasoning as
    # ingestion_router.py's bulk upsert: ON CONFLICT DO UPDATE keeps the EXISTING row's
    # id, not a freshly generated one, so the real id must be read back before chunking
    # against it (a fire-and-forget insert would risk chunking against the wrong id).
    doc_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
        row = await session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, source_app, resource_category, resource_type, external_id,
                    title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                ) VALUES (
                    :id, :tenant_id, 'github', :category, :type, :ext_id,
                    :title, :content, :s3_bucket, :s3_key, TRUE, :bytes_len
                ) ON CONFLICT (tenant_id, source_app, external_id) DO UPDATE
                SET content = EXCLUDED.content,
                    file_size_bytes = EXCLUDED.file_size_bytes,
                    updated_at = now()
                RETURNING id
            """),
            {
                "id": doc_id,
                "tenant_id": tenant_id,
                "category": resource_category,
                "type": resource_type,
                "ext_id": external_id,
                "title": title,
                "content": clean_content[:5000],
                "s3_bucket": s3_storage.bucket_name,
                "s3_key": s3_key,
                "bytes_len": file_bytes_len,
            },
        )
        real_doc_id = str(row.scalar_one())

        # Update sync_statuses counter
        await session.execute(
            text("""
                INSERT INTO sync_statuses (tenant_id, source_app, status, total_items_synced)
                VALUES (:tenant_id, 'github', 'synced', 1)
                ON CONFLICT (tenant_id, source_app) DO UPDATE
                SET total_items_synced = sync_statuses.total_items_synced + 1,
                    last_synced_at = now(),
                    status = 'synced',
                    updated_at = now()
            """),
            {"tenant_id": tenant_id},
        )
        await session.commit()

    # Real bug fixed 2026-08-20: this endpoint used to stop here — the event was
    # stored but never chunked or embedded, so a webhook-ingested GitHub event was
    # write-only, permanently unretrievable in chat. Real chunk_embed_and_store call,
    # same as every other real ingestion path (upload, connector sync, Slack/WhatsApp
    # webhooks) — using the FULL clean_content, not the 5000-char-truncated copy
    # stored in the documents row, so nothing beyond that limit silently vanishes.
    from app.processors.ingestion_pipeline import chunk_embed_and_store
    await chunk_embed_and_store(tenant_id=tenant_id, document_id=real_doc_id, full_text=clean_content, resource_category=resource_category)

    return {
        "status": "received",
        "event": event_type,
        "title": title,
        "s3_key": s3_key,
        "bytes_compressed": file_bytes_len,
        "tenant_id": tenant_id,
        "delivery_id": delivery_id,
    }


@router.get("/github/health")
async def webhook_health():
    """Quick health check endpoint for webhook receiver."""
    return {"status": "ok", "receiver": "github_webhook", "message": "Webhook receiver is live and listening."}


# ══════════════════════════════════════════════════════════════════════════
# WhatsApp Business Cloud API webhook — the ONLY real ingestion path for this
# connector (2026-08-20) ══════════════════════════════════════════════════════════════════════════
# Verified live: WhatsApp Cloud API has no synchronous "give me messages" endpoint —
# both new messages and the real 180-day history backfill (if the business has opted
# in on their side) arrive here, not via WhatsAppConnector.list_resources().
# Per-tenant URL (like the Slack webhook) — each tenant's WhatsApp Business App has
# its own app_secret and verify_token, so a per-tenant path resolves the right ones
# before any verification is attempted, same reasoning as the Slack webhook.

async def _get_whatsapp_config(tenant_id: str) -> Optional[dict]:
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("SELECT config FROM oauth_tokens WHERE tenant_id = :t AND source_app = 'whatsapp'"),
            {"t": tenant_id},
        )
        row = res.fetchone()
    return row[0] if row and row[0] else None


@router.get("/whatsapp/{tenant_id}")
async def whatsapp_webhook_verify(
    tenant_id: str,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Real Meta verification handshake: echo back hub.challenge only if
    hub.verify_token matches this tenant's real stored value. Meta calls this once
    when the webhook URL is saved in the App Dashboard."""
    config = await _get_whatsapp_config(tenant_id)
    if not config or not config.get("verify_token"):
        raise HTTPException(status_code=404, detail="No WhatsApp webhook configured for this tenant.")

    if hub_mode != "subscribe" or hub_verify_token != config["verify_token"]:
        raise HTTPException(status_code=403, detail="Verification token mismatch.")

    return PlainTextResponse(content=hub_challenge or "")


def _verify_whatsapp_signature(app_secret: str, payload_bytes: bytes, signature_header: str) -> bool:
    """Same real HMAC-SHA256 contract as verify_github_signature above — Meta signs
    the same way GitHub does."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_sig = "sha256=" + hmac.new(app_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, signature_header)


@router.post("/whatsapp/{tenant_id}")
async def whatsapp_webhook_receive(
    tenant_id: str,
    request: Request,
    x_hub_signature_256: str = Header(None),
):
    """Real message ingestion: real signature verification -> real payload parsing
    (entry -> changes -> value -> messages, verified live against Meta's documented
    schema) -> real chunk_embed_and_store, so an incoming message is retrievable
    within moments, same standard as the Slack webhook."""
    config = await _get_whatsapp_config(tenant_id)
    if not config or not config.get("app_secret"):
        raise HTTPException(status_code=404, detail="No WhatsApp webhook configured for this tenant.")

    payload_bytes = await request.body()
    if not _verify_whatsapp_signature(config["app_secret"], payload_bytes, x_hub_signature_256 or ""):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp webhook signature.")

    payload = json.loads(payload_bytes)
    ingested_count = 0

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    # Real, honest scope boundary: media/interactive/location message
                    # types need their own real handling (download + OCR/transcription
                    # for media) rather than being silently dropped as if processed —
                    # skipped explicitly here, not fixed as part of this connector.
                    continue
                text_content = (msg.get("text") or {}).get("body", "")
                if not text_content.strip():
                    continue

                sender = msg.get("from", "unknown")
                msg_id = msg.get("id", str(uuid.uuid4()))
                clean_content = pii_redactor.redact_secrets(text_content)

                s3_key, file_bytes_len = s3_storage.save_raw_json(
                    tenant_id=tenant_id, source_app="whatsapp", resource_type="message",
                    external_id=msg_id, raw_payload=msg,
                )

                async with async_session_factory() as session:
                    await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
                    doc_row = await session.execute(
                        text("""
                            INSERT INTO documents (
                                id, tenant_id, source_app, resource_category, resource_type, external_id,
                                title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                            ) VALUES (
                                :id, :tid, 'whatsapp', 'chat_message', 'message', :ext_id,
                                :title, :content, :s3_bucket, :s3_key, TRUE, :bytes_len
                            ) ON CONFLICT (tenant_id, source_app, external_id) DO UPDATE
                            SET content = EXCLUDED.content, updated_at = now()
                            RETURNING id
                        """),
                        {
                            "id": str(uuid.uuid4()), "tid": tenant_id, "ext_id": msg_id,
                            "title": f"WhatsApp message from {sender}", "content": clean_content,
                            "s3_bucket": s3_storage.bucket_name, "s3_key": s3_key, "bytes_len": file_bytes_len,
                        },
                    )
                    real_doc_id = str(doc_row.scalar_one())
                    await session.execute(
                        text("""
                            INSERT INTO sync_statuses (tenant_id, source_app, status, total_items_synced)
                            VALUES (:tid, 'whatsapp', 'synced', 1)
                            ON CONFLICT (tenant_id, source_app) DO UPDATE
                            SET total_items_synced = sync_statuses.total_items_synced + 1,
                                last_synced_at = now(), status = 'synced', updated_at = now()
                        """),
                        {"tid": tenant_id},
                    )
                    await session.commit()

                from app.processors.ingestion_pipeline import chunk_embed_and_store
                await chunk_embed_and_store(tenant_id=tenant_id, document_id=real_doc_id, full_text=clean_content, resource_category="chat_message")
                ingested_count += 1

    return {"status": "received", "messages_ingested": ingested_count}


# ══════════════════════════════════════════════════════════════════════════
# Slack Events API — real-time live sync (2026-08-20)
# ══════════════════════════════════════════════════════════════════════════
# One URL per tenant (/webhooks/slack/{tenant_id}), registered as that tenant's own
# Slack App's Event Subscriptions Request URL. This is deliberate, not incidental:
# with one shared URL across tenants, verifying a request's signature would require
# guessing which tenant's signing secret to check against before the payload is even
# parsed (Slack signs with each app's own secret, and different tenants have
# different apps under the approved bot-token-per-tenant model). A per-tenant path
# means the right secret is known before verification even starts — no ambiguity,
# no accidentally trusting an unverified payload while sniffing for team_id first.
#
# NOT verified against a real Slack workspace — this codebase has no way to receive
# real internet traffic in this local environment, and no real Slack signing secret
# was provided to test against. The URL-verification handshake and signature check
# follow Slack's documented contract exactly, but that's "built correct to spec," not
# "proven against a real Slack Events subscription."

def _verify_slack_signature(signing_secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """HMAC-SHA256 per Slack's documented Events API signing contract:
    basestring = "v0:{timestamp}:{body}", signature = "v0=" + HMAC-SHA256(secret, basestring)."""
    if not timestamp or not signature:
        return False
    # Reject stale requests (Slack recommends 5 minutes) — real replay-attack protection.
    try:
        if abs(time.time() - float(timestamp)) > 60 * 5:
            return False
    except ValueError:
        return False
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(signing_secret.encode("utf-8"), basestring.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/slack/{tenant_id}")
async def slack_webhook(
    tenant_id: str,
    request: Request,
    x_slack_signature: str = Header(None),
    x_slack_request_timestamp: str = Header(None),
):
    """Real-time Slack Events receiver for one tenant. Handles the required
    url_verification handshake, then real message.channel events -> real
    chunk_embed_and_store, so new messages are retrievable within moments instead of
    waiting for the next bounded backfill run."""
    body_bytes = await request.body()

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        res = await session.execute(
            text("SELECT config FROM oauth_tokens WHERE tenant_id = :tid AND source_app = 'slack'"),
            {"tid": tenant_id},
        )
        row = res.fetchone()

    if not row or not row[0] or not row[0].get("signing_secret"):
        # Honest rejection — never process an event we can't verify, and never guess
        # at a secret that wasn't actually configured.
        raise HTTPException(status_code=404, detail="No Slack signing secret configured for this tenant.")

    signing_secret = row[0]["signing_secret"]
    if not _verify_slack_signature(signing_secret, x_slack_request_timestamp or "", body_bytes, x_slack_signature or ""):
        raise HTTPException(status_code=401, detail="Invalid Slack request signature.")

    payload = json.loads(body_bytes)

    # Required handshake: Slack sends this once when the Request URL is first saved,
    # and expects the raw challenge string echoed back within 3 seconds.
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event", {})
    if payload.get("type") != "event_callback" or event.get("type") != "message" or event.get("subtype"):
        # Not a real new-message event (could be an edit, a bot message, a reaction,
        # etc.) — acknowledge without fabricating processing that didn't happen.
        return {"status": "ignored"}

    text_content = event.get("text", "")
    if not text_content.strip():
        return {"status": "ignored", "reason": "empty_text"}

    channel_id = event.get("channel")
    doc_id = str(uuid.uuid4())
    ext_id = f"{channel_id}_{event.get('ts')}"
    clean_content = pii_redactor.redact_secrets(text_content)

    s3_key, file_bytes_len = s3_storage.save_raw_json(
        tenant_id=tenant_id, source_app="slack", resource_type="message",
        external_id=ext_id, raw_payload=event,
    )

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        doc_row = await session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, source_app, resource_category, resource_type, external_id,
                    title, content, s3_bucket, s3_key, is_compressed, file_size_bytes, resource_group_id
                ) VALUES (
                    :id, :tid, 'slack', 'chat_message', 'message', :ext_id,
                    :title, :content, :s3_bucket, :s3_key, TRUE, :bytes_len, :channel_id
                ) ON CONFLICT (tenant_id, source_app, external_id) DO UPDATE
                SET content = EXCLUDED.content, updated_at = now()
                RETURNING id
            """),
            {
                "id": doc_id, "tid": tenant_id, "ext_id": ext_id,
                "title": f"#{channel_id} message", "content": clean_content,
                "s3_bucket": s3_storage.bucket_name, "s3_key": s3_key,
                "bytes_len": file_bytes_len, "channel_id": channel_id,
            },
        )
        real_doc_id = str(doc_row.scalar_one())
        await session.execute(
            text("""
                INSERT INTO sync_statuses (tenant_id, source_app, status, total_items_synced)
                VALUES (:tid, 'slack', 'synced', 1)
                ON CONFLICT (tenant_id, source_app) DO UPDATE
                SET total_items_synced = sync_statuses.total_items_synced + 1,
                    last_synced_at = now(), status = 'synced', updated_at = now()
            """),
            {"tid": tenant_id},
        )
        await session.commit()

    # Real chunk/embed/store — a webhook-ingested message is retrievable immediately,
    # not just stored. (The pre-existing GitHub webhook handler above does NOT do
    # this — it stores raw payloads that are never chunked/embedded, so webhook-driven
    # GitHub events are currently write-only and never retrievable in chat. Flagged,
    # not fixed here — out of scope for the Slack connector work.)
    from app.processors.ingestion_pipeline import chunk_embed_and_store
    await chunk_embed_and_store(tenant_id=tenant_id, document_id=real_doc_id, full_text=clean_content, resource_category="chat_message")

    return {"status": "received", "document_id": real_doc_id}
