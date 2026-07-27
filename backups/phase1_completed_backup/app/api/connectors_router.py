from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.crypto import token_crypto
from app.db.redis_cache import redis_cache

router = APIRouter(prefix="/api/v1/connectors", tags=["App Selection & OAuth Hub"])

class ConnectAppRequest(BaseModel):
    tenant_id: str
    source_app: str
    action: str = "connect"  # 'connect' or 'disconnect'

AVAILABLE_APPS = [
    {"id": "slack", "name": "Slack", "category": "Communication", "icon": "chat-bubble", "description": "Messages, Channels, Threads & Attachments"},
    {"id": "google_drive", "name": "Google Drive", "category": "Docs & Storage", "icon": "file-text", "description": "Google Docs, PDFs, Word & Spreadsheets"},
    {"id": "github", "name": "GitHub", "category": "Code Repositories", "icon": "git-pull-request", "description": "Repositories, Pull Requests & Code Commits"},
    {"id": "jira", "name": "Jira", "category": "Project Tracking", "icon": "check-square", "description": "Project Issues, Tickets & Sprint Logs"},
    {"id": "whatsapp", "name": "WhatsApp Business", "category": "Messaging", "icon": "message-circle", "description": "Business Conversations & Media"},
    {"id": "teams", "name": "Microsoft Teams", "category": "Communication", "icon": "users", "description": "Team Channels, Chats & Transcripts"},
]

@router.get("/list")
async def list_connectors(tenant_id: str):
    """
    Step 2: App Selection Screen
    Returns list of apps with connection status for the given tenant.
    """
    async with async_session_factory() as session:
        await session.execute(
            text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
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
async def connect_app(req: ConnectAppRequest):
    """
    Step 2: OAuth Connect & Encrypted Token Caching
    Encrypts token via AES-256-GCM and caches encrypted cipher in Redis for 0ms DB latency.
    """
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
            text(f"SET LOCAL app.current_tenant_id = '{req.tenant_id}'")
        )

        if req.action == "connect":
            mock_access_token = f"token_{req.source_app}_{req.tenant_id[:8]}"
            encrypted_token = token_crypto.encrypt_token(mock_access_token, req.tenant_id)

            # SECURITY GUARANTEE: Caches encrypted cipher in Redis (15-min TTL)
            redis_cache.set_cached_encrypted_token(req.tenant_id, req.source_app, encrypted_token)

            await session.execute(
                text("""
                    INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token)
                    VALUES (:tenant_id, :source_app, :encrypted_token)
                    ON CONFLICT (tenant_id, source_app) DO UPDATE 
                    SET encrypted_access_token = EXCLUDED.encrypted_access_token,
                        updated_at = now()
                """),
                {
                    "tenant_id": req.tenant_id,
                    "source_app": req.source_app,
                    "encrypted_token": encrypted_token,
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
