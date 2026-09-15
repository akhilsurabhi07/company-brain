"""
Real per-tenant MCP API key management — Module 10 (external AI connectivity).
==================================================================================
Only the SHA-256 hash of a key is ever stored. The raw key is returned exactly once,
at creation time, and can never be recovered afterward — same principle as GitHub's
or Stripe's API keys, and deliberately different from oauth_tokens (which uses
reversible AES-256-GCM, because ingestion needs to read those back to call real APIs;
an MCP key only ever needs to be *compared*, never read back, so hashing is the
correct primitive here, not encryption).
"""
import hashlib
import secrets
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token

router = APIRouter(prefix="/api/v1/mcp/keys", tags=["MCP API Keys"])

KEY_PREFIX = "cbmcp_"  # identifiable prefix, same convention as sk-/ghp_/xoxb- etc.


class CreateMcpKeyRequest(BaseModel):
    tenant_id: str
    name: Optional[str] = "Default MCP Key"


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


@router.post("")
async def create_mcp_key(req: CreateMcpKeyRequest, token=Depends(require_authenticated_tenant)):
    """Generates a real, cryptographically random key (256 bits of entropy) and
    returns it once. Only its hash is persisted."""
    req.tenant_id = verify_tenant_matches_token(req.tenant_id, token)
    raw_key = KEY_PREFIX + secrets.token_urlsafe(32)
    key_hash = _hash_key(raw_key)

    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Enterprise Tenant', :d) ON CONFLICT (id) DO NOTHING"),
            {"id": req.tenant_id, "d": f"tenant_{req.tenant_id[:8]}.com"},
        )
        await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(req.tenant_id)})
        row = await session.execute(
            text("INSERT INTO mcp_api_keys (tenant_id, key_hash, name) VALUES (:tid, :hash, :name) RETURNING id, created_at"),
            {"tid": req.tenant_id, "hash": key_hash, "name": req.name or "Default MCP Key"},
        )
        key_row = row.fetchone()
        await session.commit()

    return {
        "id": str(key_row.id),
        "api_key": raw_key,
        "created_at": str(key_row.created_at),
        "warning": "This key is shown only once. Store it now — it cannot be retrieved again, only revoked and replaced.",
    }


@router.get("")
async def list_mcp_keys(tenant_id: str = Query(...), token=Depends(require_authenticated_tenant)):
    """Lists real key metadata for a tenant — never the raw key or its hash."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
        res = await session.execute(
            text("""
                SELECT id, name, created_at, last_used_at, revoked_at
                FROM mcp_api_keys WHERE tenant_id = :tid ORDER BY created_at DESC
            """),
            {"tid": tenant_id},
        )
        keys = [
            {
                "id": str(r.id), "name": r.name, "created_at": str(r.created_at),
                "last_used_at": str(r.last_used_at) if r.last_used_at else None,
                "revoked": r.revoked_at is not None,
            }
            for r in res.fetchall()
        ]
    return {"tenant_id": tenant_id, "keys": keys}


@router.delete("/{key_id}")
async def revoke_mcp_key(key_id: str, tenant_id: str = Query(...), token=Depends(require_authenticated_tenant)):
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
        res = await session.execute(
            text("UPDATE mcp_api_keys SET revoked_at = now() WHERE id = :kid AND tenant_id = :tid AND revoked_at IS NULL RETURNING id"),
            {"kid": key_id, "tid": tenant_id},
        )
        revoked = res.fetchone()
        await session.commit()

    if not revoked:
        raise HTTPException(status_code=404, detail="Key not found, already revoked, or belongs to a different tenant.")
    return {"status": "revoked", "id": key_id}
