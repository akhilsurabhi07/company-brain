"""
Multi-Tenant Auth Handler — Module 5 EKAP
=========================================
Validates real credentials and resolves a real tenant/user identity.

Real integration (2026-08-22): previously this authenticated against a
hardcoded dict of 3 simulated API keys (`key_tenant_alpha`, `key_tenant_beta`,
`key_demo`) mapping to fabricated identities — completely disconnected from
real users, tenants, or the live auth system. Replaced with two real,
already-live credential paths:

  1. Bearer token -> the real JWT engine (app.security.jwt_auth.jwt_engine),
     the same HMAC-SHA256-signed token every other endpoint in the product
     already trusts (tenant_id/user_id/email/role claims, real expiration
     check, real signature verification).
  2. X-API-Key -> the real, live, hash-only `mcp_api_keys` table (the same
     one app/api/mcp_server_router.py's `_resolve_tenant_from_bearer()`
     already uses for MCP), SHA-256 hash lookup, tenant-scoped only.

IMPORTANT: `mcp_api_keys` is tenant-scoped only — it carries no user_id or
role. MCP key creation (app/api/mcp_keys_router.py::create_mcp_key) is not
admin-gated: any authenticated tenant member can create one. Treating an
API key as admin-equivalent would therefore be a real privilege-escalation
path, so API-key-authenticated requests are always mapped to the
least-privileged real role ("member"), never "admin".
"""
import hashlib
from typing import Optional
from sqlalchemy import text
from app.gateway.domain.auth import UserIdentity
from app.gateway.common.exceptions import AuthenticationException
from app.security.jwt_auth import jwt_engine
from app.db.database import async_session_factory


class AuthHandler:
    """Authenticates request credentials and resolves a real tenant identity."""

    async def authenticate(self, api_key: Optional[str] = None, bearer_token: Optional[str] = None) -> UserIdentity:
        if bearer_token:
            token = bearer_token
            if token.lower().startswith("bearer "):
                token = token[7:].strip()
            payload = jwt_engine.decode_access_token(token)
            if payload is None:
                raise AuthenticationException("Invalid or expired bearer token.")
            tenant_id = payload.get("tenant_id")
            user_id = payload.get("user_id")
            if not tenant_id or not user_id:
                raise AuthenticationException("Bearer token is missing required claims.")
            role = payload.get("role") or "member"
            return UserIdentity(
                user_id=user_id,
                tenant_id=tenant_id,
                roles=[role],
                clearance_level="Confidential" if role == "admin" else "Internal",
            )

        if api_key:
            key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
            async with async_session_factory() as session:
                res = await session.execute(
                    text("SELECT id, tenant_id FROM mcp_api_keys WHERE key_hash = :hash AND revoked_at IS NULL"),
                    {"hash": key_hash},
                )
                row = res.fetchone()
                if not row:
                    raise AuthenticationException("Invalid or revoked API key.")
                await session.execute(
                    text("UPDATE mcp_api_keys SET last_used_at = now() WHERE id = :kid"),
                    {"kid": row.id},
                )
                await session.commit()

            # mcp_api_keys carries no user_id/role — least-privilege mapping only.
            return UserIdentity(
                user_id=f"api_key:{str(row.id)[:8]}",
                tenant_id=str(row.tenant_id),
                roles=["member"],
                clearance_level="Internal",
            )

        # Fail closed. There is no safe default identity for a missing or
        # invalid credential — it must be rejected, never identity-forged.
        raise AuthenticationException("Invalid or missing authentication credentials.")


auth_handler = AuthHandler()
