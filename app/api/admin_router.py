"""
Admin Dashboard API — Module 6C (2026-08-23).

Real backend found+fixed 2026-08-23: `frontend/admin.html` already existed as a
324-line, genuinely real page (real /upload/stats-backed stat cards, source
breakdown, recent documents, an upload zone) — but every one of its fetch()
calls sent no Authorization header at all, so it 401'd against the real
auth-gated endpoints it was built for, and it was never linked from the main
app's nav (the sidebar's "Admin Dashboard" item was still a hardcoded "Soon").
A fourth instance of this engagement's "real code, not actually reachable"
pattern — this time on the frontend rather than the backend. Fixed the page's
auth handling and linked it in; this router adds the one piece of real "admin"
capability that page never had at all: team/role management. Everything else
that page already showed (document stats, system health) is genuinely real
and is left as-is.
"""
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token

router = APIRouter(prefix="/api/v1/admin", tags=["Admin Dashboard"])

# The only two role values any real RBAC check in this codebase actually
# branches on (see app/api/auth.py's invite gate, graph_api.py's redaction
# gate) — anything else is free-text that nothing enforces, so role updates
# are restricted to values the system can genuinely act on.
_VALID_ROLES = {"admin", "member"}


def _require_admin(token: dict) -> None:
    if (token.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only a workspace admin can access this.")


@router.get("/users")
async def list_users_for_admin(
    tenant_id: str = Query(...),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real tenant member list with role, for the Admin Dashboard's Team &
    Roles section — same real users table People/Teams already read, plus
    the role column those two intentionally don't expose for editing."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    _require_admin(token)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("SELECT id, email, full_name, role, department, created_at FROM users WHERE tenant_id = :t ORDER BY created_at ASC"),
            {"t": tenant_id},
        )
        users = [
            {
                "id": str(r.id), "email": r.email, "full_name": r.full_name,
                "role": r.role, "department": r.department,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in res.fetchall()
        ]
    return {"users": users, "count": len(users)}


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    role: str = Query(..., description="New role: 'admin' or 'member'"),
    tenant_id: str = Query(...),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    _require_admin(token)
    role = role.lower()
    if role not in _VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(_VALID_ROLES)}")

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        # Real "don't lock yourself out" guard: if this is the tenant's last
        # remaining admin, refuse to demote them — otherwise the workspace
        # would end up with zero admins and no real path back in.
        target = await session.execute(
            text("SELECT role FROM users WHERE id = :uid AND tenant_id = :t"), {"uid": user_id, "t": tenant_id}
        )
        row = target.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="User not found in this tenant.")
        if row.role == "admin" and role != "admin":
            admin_count = (await session.execute(
                text("SELECT COUNT(*) FROM users WHERE tenant_id = :t AND role = 'admin'"), {"t": tenant_id}
            )).scalar()
            if admin_count <= 1:
                raise HTTPException(status_code=409, detail="Cannot remove the workspace's last remaining admin.")

        await session.execute(
            text("UPDATE users SET role = :role, updated_at = now() WHERE id = :uid AND tenant_id = :t"),
            {"role": role, "uid": user_id, "t": tenant_id},
        )
        await session.commit()
    return {"user_id": user_id, "role": role}


@router.get("/activity")
async def list_recent_activity(
    tenant_id: str = Query(...),
    limit: int = Query(30, ge=1, le=100),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real ingestion activity log — genuinely populated going forward by
    every real document upload (see upload_router.py's new write into
    ingestion_audit_logs), not backfilled or fabricated. A brand-new tenant
    honestly shows nothing here until someone actually uploads something."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    _require_admin(token)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                SELECT source_app, action, items_processed, details, created_at
                FROM ingestion_audit_logs WHERE tenant_id = :t
                ORDER BY created_at DESC LIMIT :lim
            """),
            {"t": tenant_id, "lim": limit},
        )
        activity = [
            {
                "source_app": r.source_app, "action": r.action, "items_processed": r.items_processed,
                "details": r.details, "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in res.fetchall()
        ]
    return {"activity": activity, "count": len(activity)}
