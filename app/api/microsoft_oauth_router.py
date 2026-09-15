"""
Real Microsoft identity platform OAuth 2.0 flow — SharePoint connector.
===========================================================================
Same reasoning as Google Drive: delegated permissions + a real user's OAuth consent
(scoped to what that user can actually see), not "application permissions" / app-only
access — Microsoft's equivalent of Google's domain-wide delegation, where an admin
grants tenant-wide access with no specific user in the loop. Delegated is the safer,
more scoped default; app-only would need its own explicit decision the same way
Google's DWD did, and hasn't been asked for here.

Microsoft's refresh tokens behave like Google's (reusable, don't rotate on every use)
— unlike Atlassian's. Verified against learn.microsoft.com, 2026-08-20.
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

router = APIRouter(prefix="/api/v1/connectors/oauth", tags=["Microsoft OAuth"])

MS_AUTH_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

# offline_access is required to receive a refresh_token. Sites.Read.All covers real
# SharePoint site content (not just the caller's own OneDrive).
SHAREPOINT_SCOPES = "offline_access Files.Read.All Sites.Read.All"

_STATE_AAD = "oauth_state_sharepoint"
_STATE_TTL_SECONDS = 600


@router.get("/sharepoint/start")
async def start_sharepoint_oauth(tenant_id: str = Query(...)):
    if not settings.MICROSOFT_OAUTH_CLIENT_ID or not settings.MICROSOFT_OAUTH_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Microsoft OAuth is not configured on this server (MICROSOFT_OAUTH_CLIENT_ID/SECRET missing). "
                   "An admin must register an app at entra.microsoft.com first.",
        )

    state_payload = json.dumps({"tenant_id": tenant_id, "ts": time.time()})
    state = token_crypto.encrypt_token(state_payload, _STATE_AAD)

    params = {
        "client_id": settings.MICROSOFT_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.MICROSOFT_OAUTH_REDIRECT_URI,
        "scope": SHAREPOINT_SCOPES,
        "state": state,
        "prompt": "consent",
    }
    query = str(httpx.QueryParams(params))
    return RedirectResponse(url=f"{MS_AUTH_ENDPOINT}?{query}")


@router.get("/sharepoint/callback")
async def sharepoint_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Microsoft OAuth was denied or failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state from Microsoft's callback.")

    try:
        state_payload = json.loads(token_crypto.decrypt_token(state, _STATE_AAD))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or tampered OAuth state.")
    if time.time() - state_payload.get("ts", 0) > _STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="OAuth state expired — please restart the connection flow.")

    tenant_id = state_payload["tenant_id"]

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(MS_TOKEN_ENDPOINT, data={
            "client_id": settings.MICROSOFT_OAUTH_CLIENT_ID,
            "client_secret": settings.MICROSOFT_OAUTH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.MICROSOFT_OAUTH_REDIRECT_URI,
            "scope": SHAREPOINT_SCOPES,
        })
        token_data = resp.json()

    if "access_token" not in token_data:
        raise HTTPException(status_code=400, detail=f"Microsoft token exchange failed: {token_data.get('error_description', token_data.get('error', 'unknown_error'))}")

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Microsoft did not return a refresh_token — offline_access scope may not have been granted.")

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
                VALUES (:tid, 'sharepoint', :tok, '{}'::jsonb)
                ON CONFLICT (tenant_id, source_app) DO UPDATE
                SET encrypted_access_token = EXCLUDED.encrypted_access_token, updated_at = now()
            """),
            {"tid": tenant_id, "tok": encrypted_refresh},
        )
        await session.execute(
            text("INSERT INTO sync_statuses (tenant_id, source_app, status) VALUES (:tid, 'sharepoint', 'idle') ON CONFLICT (tenant_id, source_app) DO NOTHING"),
            {"tid": tenant_id},
        )
        await session.commit()

    return {"status": "success", "message": "SharePoint connected — real refresh token stored.", "tenant_id": tenant_id}
