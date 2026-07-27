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
from fastapi import APIRouter, Request, HTTPException, Header
from sqlalchemy import text
from app.db.database import async_session_factory
from app.storage.s3_storage import s3_storage
from app.processors.pii_redactor import pii_redactor

router = APIRouter(prefix="/api/v1/webhooks", tags=["Live Webhook Receivers"])

# GitHub Webhook secret — must match what you set in GitHub repo settings
GITHUB_WEBHOOK_SECRET = "company_brain_github_secret_2026"


def verify_github_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    Verifies GitHub webhook payload using HMAC-SHA256 signature.
    GitHub sends: X-Hub-Signature-256: sha256=<hex_digest>
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_sig = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_sig, signature_header)


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None),
    x_github_event: str = Header(None),
    x_github_delivery: str = Header(None),
):
    """
    Phase 2: Live GitHub Webhook Event Receiver.
    Receives push, pull_request, issues, create events in real time.
    Verifies HMAC signature → Redacts PII → Compresses → Uploads S3 → Indexes SQL.
    """
    payload_bytes = await request.body()

    # Step 1: Verify HMAC Signature
    if not verify_github_signature(payload_bytes, x_hub_signature_256 or ""):
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

    # Step 4: Determine tenant from repository (in production: look up from oauth_tokens table)
    async with async_session_factory() as session:
        # Try to match tenant by repo domain
        res_tenant = await session.execute(
            text("SELECT id FROM tenants LIMIT 1")
        )
        tenant_row = res_tenant.fetchone()
        tenant_id = str(tenant_row[0]) if tenant_row else "00000000-0000-0000-0000-000000000001"

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

    # Step 7: Index metadata in PostgreSQL
    async with async_session_factory() as session:
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
        await session.execute(
            text("""
                INSERT INTO documents (
                    tenant_id, source_app, resource_category, resource_type, external_id,
                    title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                ) VALUES (
                    :tenant_id, 'github', :category, :type, :ext_id,
                    :title, :content, :s3_bucket, :s3_key, TRUE, :bytes_len
                ) ON CONFLICT (tenant_id, source_app, external_id) DO UPDATE
                SET content = EXCLUDED.content,
                    file_size_bytes = EXCLUDED.file_size_bytes,
                    updated_at = now()
            """),
            {
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
