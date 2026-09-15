"""
Real Atlassian OAuth 2.0 (3LO) flow — Jira connector.
========================================================
Same reasoning as Google Drive (see google_oauth_router.py): Jira Cloud does support
a simple API-token + email basic-auth model, but Atlassian's own docs state that
collecting API tokens from customers for a third-party app doesn't comply with their
security requirements for cloud apps. Real OAuth 2.0 (3LO) it is.

Real difference from Google, verified live against developer.atlassian.com
(2026-08-20): Atlassian refresh tokens ROTATE on every use — each exchange
invalidates the previous refresh token and issues a new one that must be persisted,
or the next sync fails outright. See ingestion_router.py's post-authenticate()
persistence step, which handles this generically for any connector that returns an
updated refresh_token.

Also real and Jira-specific: there's no "the tenant tells us their site" step — the
real Jira site (cloudId) is discovered via a real call to
api.atlassian.com/oauth/token/accessible-resources right after the token exchange,
and stored in oauth_tokens.config (same JSONB slot GitHub uses for owner/repo).
"""
import json
import time
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from app.config import settings
from app.db.database import async_session_factory
from app.security.crypto import token_crypto

router = APIRouter(prefix="/api/v1/connectors/oauth", tags=["Jira OAuth"])

ATLASSIAN_AUTH_ENDPOINT = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_ENDPOINT = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_ACCESSIBLE_RESOURCES = "https://api.atlassian.com/oauth/token/accessible-resources"

# offline_access is required to receive a refresh_token at all.
JIRA_SCOPES = "read:jira-work read:jira-user offline_access"

_STATE_AAD = "oauth_state_jira"
_STATE_TTL_SECONDS = 600


@router.get("/jira/start")
async def start_jira_oauth(tenant_id: str = Query(...)):
    if not settings.JIRA_OAUTH_CLIENT_ID or not settings.JIRA_OAUTH_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Jira OAuth is not configured on this server (JIRA_OAUTH_CLIENT_ID/SECRET missing). "
                   "An admin must create an OAuth 2.0 (3LO) app at developer.atlassian.com first.",
        )

    state_payload = json.dumps({"tenant_id": tenant_id, "ts": time.time()})
    state = token_crypto.encrypt_token(state_payload, _STATE_AAD)

    params = {
        "audience": "api.atlassian.com",
        "client_id": settings.JIRA_OAUTH_CLIENT_ID,
        "scope": JIRA_SCOPES,
        "redirect_uri": settings.JIRA_OAUTH_REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    query = str(httpx.QueryParams(params))
    return RedirectResponse(url=f"{ATLASSIAN_AUTH_ENDPOINT}?{query}")


@router.get("/jira/callback")
async def jira_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Jira OAuth was denied or failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state from Atlassian's callback.")

    try:
        state_payload = json.loads(token_crypto.decrypt_token(state, _STATE_AAD))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or tampered OAuth state.")
    if time.time() - state_payload.get("ts", 0) > _STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="OAuth state expired — please restart the connection flow.")

    tenant_id = state_payload["tenant_id"]

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(ATLASSIAN_TOKEN_ENDPOINT, json={
            "grant_type": "authorization_code",
            "client_id": settings.JIRA_OAUTH_CLIENT_ID,
            "client_secret": settings.JIRA_OAUTH_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.JIRA_OAUTH_REDIRECT_URI,
        })
        token_data = resp.json()

    if "error" in token_data or "access_token" not in token_data:
        raise HTTPException(status_code=400, detail=f"Jira token exchange failed: {token_data.get('error_description', token_data.get('error', 'unknown_error'))}")

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Atlassian did not return a refresh_token — offline_access scope may not have been granted. "
                   "Revoke existing access at id.atlassian.com/manage-profile/apps and try connecting again.",
        )

    # Real discovery of which Jira site was actually authorized — never guessed.
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(ATLASSIAN_ACCESSIBLE_RESOURCES, headers={"Authorization": f"Bearer {token_data['access_token']}"})
        resources = resp.json()

    if not resources:
        raise HTTPException(status_code=400, detail="No accessible Jira site was granted during authorization.")
    cloud_id = resources[0]["id"]
    site_url = resources[0].get("url", "")

    encrypted_refresh = token_crypto.encrypt_token(refresh_token, tenant_id)
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Enterprise Tenant', :d) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "d": f"tenant_{tenant_id[:8]}.com"},
        )
        await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
        await session.execute(
            text("""
                INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config)
                VALUES (:tid, 'jira', :tok, CAST(:config AS jsonb))
                ON CONFLICT (tenant_id, source_app) DO UPDATE
                SET encrypted_access_token = EXCLUDED.encrypted_access_token, config = EXCLUDED.config, updated_at = now()
            """),
            {"tid": tenant_id, "tok": encrypted_refresh, "config": json.dumps({"cloud_id": cloud_id, "site_url": site_url})},
        )
        await session.execute(
            text("INSERT INTO sync_statuses (tenant_id, source_app, status) VALUES (:tid, 'jira', 'idle') ON CONFLICT (tenant_id, source_app) DO NOTHING"),
            {"tid": tenant_id},
        )
        await session.commit()

    return {"status": "success", "message": f"Jira connected to {site_url} — real refresh token stored.", "tenant_id": tenant_id, "cloud_id": cloud_id}
