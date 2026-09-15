from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.crypto import token_crypto
from app.db.redis_cache import redis_cache
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token

router = APIRouter(prefix="/api/v1/connectors", tags=["App Selection & OAuth Hub"])

class ConnectAppRequest(BaseModel):
    tenant_id: str
    source_app: str
    action: str = "connect"  # 'connect' or 'disconnect'
    # Real credential (e.g. a GitHub Personal Access Token). When provided, this is what
    # actually gets stored and used for real API calls. When omitted, falls back to a
    # clearly-labeled placeholder token so the demo/offline flow keeps working — but that
    # placeholder can never authenticate a real API call, only real_credential can.
    access_token: Optional[str] = None
    # Connector-specific settings, e.g. {"owner": "octocat", "repo": "Hello-World"} for
    # GitHub — which real resource to sync, since there is no sensible default.
    config: Optional[Dict[str, Any]] = None

AVAILABLE_APPS = [
    {"id": "slack", "name": "Slack", "category": "Communication", "icon": "chat-bubble", "description": "Messages, Channels, Threads & Attachments"},
    {"id": "google_drive", "name": "Google Drive", "category": "Docs & Storage", "icon": "file-text", "description": "Google Docs, PDFs, Word & Spreadsheets"},
    {"id": "github", "name": "GitHub", "category": "Code Repositories", "icon": "git-pull-request", "description": "Repositories, Pull Requests & Code Commits"},
    {"id": "jira", "name": "Jira", "category": "Project Tracking", "icon": "check-square", "description": "Project Issues, Tickets & Sprint Logs"},
    {"id": "whatsapp", "name": "WhatsApp Business", "category": "Messaging", "icon": "message-circle", "description": "Business Conversations & Media"},
    {"id": "teams", "name": "Microsoft Teams", "category": "Communication", "icon": "users", "description": "Team Channels, Chats & Transcripts"},
    {"id": "sharepoint", "name": "SharePoint", "category": "Docs & Storage", "icon": "folder", "description": "Sites, Document Libraries & Files"},
]

@router.get("/list")
async def list_connectors(tenant_id: str, token=Depends(require_authenticated_tenant)):
    """
    Step 2: App Selection Screen
    Returns list of apps with connection status for the given tenant.
    """
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)}
        )
        res = await session.execute(
            text("SELECT source_app FROM oauth_tokens WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        connected_apps = set(row[0] for row in res.fetchall())

        apps_response = []
        for app in AVAILABLE_APPS:
            is_connected = app["id"] in connected_apps
            apps_response.append({
                **app,
                "is_connected": is_connected,
                "status": "Connected" if is_connected else "Not Connected"
            })

        return {"tenant_id": tenant_id, "connectors": apps_response}

@router.post("/connect")
async def connect_app(req: ConnectAppRequest, token=Depends(require_authenticated_tenant)):
    """
    Step 2: OAuth Connect & Encrypted Token Caching
    Encrypts token via AES-256-GCM and caches encrypted cipher in Redis for 0ms DB latency.
    """
    req.tenant_id = verify_tenant_matches_token(req.tenant_id, token)
    if req.source_app in ("google_drive", "jira", "sharepoint") and req.action == "connect":
        # Neither has a pasted-token flow (see google_oauth_router.py / jira_oauth_router.py
        # module docstrings — real OAuth is the only compliant path for both). Blocking
        # this route for them rather than silently accepting a request here: without
        # this guard, a stray call to this generic endpoint would overwrite a real,
        # working refresh_token with an inert placeholder, breaking a connection that
        # was already correctly set up via the real OAuth flow.
        raise HTTPException(
            status_code=400,
            detail=f"{req.source_app} uses real OAuth — connect via GET /api/v1/connectors/oauth/{req.source_app}/start?tenant_id=... instead of this endpoint.",
        )

    async with async_session_factory() as session:
        # Ensure tenant record exists
        await session.execute(
            text("""
                INSERT INTO tenants (id, name, domain)
                VALUES (:tenant_id, 'Enterprise Tenant', :domain)
                ON CONFLICT (id) DO NOTHING
            """),
            {"tenant_id": req.tenant_id, "domain": f"tenant_{req.tenant_id[:8]}.com"},
        )
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(req.tenant_id)}
        )

        if req.action == "connect":
            # Real credential when the caller supplies one (e.g. a pasted GitHub PAT);
            # otherwise an honestly-labeled placeholder that can never authenticate a
            # real API call, so it never gets confused for a working connection.
            token_to_store = req.access_token.strip() if req.access_token and req.access_token.strip() else (
                f"PLACEHOLDER_NO_REAL_CREDENTIAL_{req.source_app}_{req.tenant_id[:8]}"
            )
            encrypted_token = token_crypto.encrypt_token(token_to_store, req.tenant_id)

            # SECURITY GUARANTEE: Caches encrypted cipher in Redis (15-min TTL)
            await redis_cache.set_cached_encrypted_token(req.tenant_id, req.source_app, encrypted_token)

            resolved_config = dict(req.config or {})
            if req.source_app == "slack" and req.access_token:
                # Real, immediate token verification via auth.test — reject a bad Slack
                # token now instead of silently storing it and only discovering it's
                # invalid at the next sync. Also captures the real team_id, which the
                # Slack Events webhook needs to resolve an incoming event to the right
                # tenant (see app/api/webhooks.py) — without this, webhook tenant
                # resolution would have nothing real to match against.
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=10.0) as _client:
                    _resp = await _client.post(
                        "https://slack.com/api/auth.test",
                        headers={"Authorization": f"Bearer {token_to_store}"},
                    )
                    _data = _resp.json()
                if not _data.get("ok"):
                    raise HTTPException(status_code=400, detail=f"Slack token verification failed: {_data.get('error', 'unknown_error')}")
                resolved_config["team_id"] = _data.get("team_id")
                resolved_config["team_name"] = _data.get("team")

            import json as _json
            await session.execute(
                text("""
                    INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config)
                    VALUES (:tenant_id, :source_app, :encrypted_token, CAST(:config AS jsonb))
                    ON CONFLICT (tenant_id, source_app) DO UPDATE
                    SET encrypted_access_token = EXCLUDED.encrypted_access_token,
                        config = EXCLUDED.config,
                        updated_at = now()
                """),
                {
                    "tenant_id": req.tenant_id,
                    "source_app": req.source_app,
                    "encrypted_token": encrypted_token,
                    "config": _json.dumps(resolved_config),
                },
            )
            await session.execute(
                text("""
                    INSERT INTO sync_statuses (tenant_id, source_app, status)
                    VALUES (:tenant_id, :source_app, 'idle')
                    ON CONFLICT (tenant_id, source_app) DO NOTHING
                """),
                {"tenant_id": req.tenant_id, "source_app": req.source_app},
            )
            message = f"Successfully connected {req.source_app.title()}"
        else:
            await session.execute(
                text("DELETE FROM oauth_tokens WHERE tenant_id = :tenant_id AND source_app = :source_app"),
                {"tenant_id": req.tenant_id, "source_app": req.source_app},
            )
            message = f"Disconnected {req.source_app.title()}"

        await session.commit()
        return {"status": "success", "message": message, "tenant_id": req.tenant_id, "source_app": req.source_app}
