"""
Shared FastAPI auth dependency for real endpoints.

Before this, auth.py's signup/login/JWT system was real and fully working in
isolation, but no other endpoint ever required it — chat, upload, graph, ingestion,
and connectors all just trusted whatever tenant_id the caller put in the request
body/query string, with zero verification the caller was actually authorized for
that tenant. Anyone who could reach the server could read/write any tenant's data.

`require_authenticated_tenant` verifies a real Bearer JWT (issued by /api/v1/auth/
signup or /login) and returns the tenant_id it was actually issued for.
`verify_tenant_matches_token` additionally checks that against a tenant_id the
client also supplied in its own request body/query, so existing request/response
shapes don't have to change — a mismatch means someone is trying to use their own
valid token to reach into a different tenant, which is rejected outright.
"""
from typing import Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.security.jwt_auth import jwt_engine

security_bearer = HTTPBearer(auto_error=False)


def require_authenticated_tenant(
    credentials: HTTPAuthorizationCredentials = Depends(security_bearer),
) -> Dict[str, Any]:
    """Validates the bearer JWT and returns its payload (tenant_id, user_id, email, role)."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization token.")
    payload = jwt_engine.decode_access_token(credentials.credentials)
    if not payload or not payload.get("tenant_id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    return payload


def verify_tenant_matches_token(claimed_tenant_id: str, token_payload: Dict[str, Any]) -> str:
    """Rejects a request whose own claimed tenant_id doesn't match the authenticated
    token's tenant_id — a valid login for Tenant A must not be usable to read/write
    Tenant B's data just by changing a request field. Returns the verified tenant_id."""
    real_tenant_id = token_payload["tenant_id"]
    if claimed_tenant_id and str(claimed_tenant_id) != str(real_tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your token isn't authorized for this tenant.",
        )
    return real_tenant_id
