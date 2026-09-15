"""
Workspace Directory API — Module 6B (2026-08-23).

Real read paths for the sidebar's "People", "Teams", and "Documents" panels
— all previously honest "Soon" placeholders with no backend concept. All
three are backed by data that already existed (the real `users` and
`documents` tables); this just adds the first read endpoints for them.
"Dashboards" deliberately has no new endpoint here — it reuses the
already-real /api/v1/knowledge/health computed metrics rather than
duplicating that work.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token

router = APIRouter(prefix="/api/v1/workspace", tags=["Workspace Directory"])


@router.get("/people")
async def list_people(
    tenant_id: str = Query(...),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real tenant member directory — email/name/role/department, the same
    real users table every other real endpoint in this product already
    trusts. No RBAC redaction needed here: this is organizational directory
    info (who's on the team), not restricted content like salary figures."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                SELECT id, email, full_name, role, department, created_at
                FROM users WHERE tenant_id = :t ORDER BY created_at ASC
            """),
            {"t": tenant_id},
        )
        people = [
            {
                "id": str(r.id), "email": r.email, "full_name": r.full_name,
                "role": r.role, "department": r.department,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in res.fetchall()
        ]
    return {"people": people, "count": len(people)}


@router.get("/teams")
async def list_teams(
    tenant_id: str = Query(...),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real "teams" derived from the users table's department column — the
    vision's fuller Teams concept (dedicated team entities, membership
    history) doesn't exist as a schema yet, so this is an honest, real
    synthesis from existing data rather than a separate fabricated concept."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                SELECT COALESCE(NULLIF(TRIM(department), ''), 'Unassigned') AS team_name,
                       id, email, full_name, role
                FROM users WHERE tenant_id = :t ORDER BY team_name, full_name
            """),
            {"t": tenant_id},
        )
        teams: Dict[str, List[Dict[str, Any]]] = {}
        for r in res.fetchall():
            teams.setdefault(r.team_name, []).append({
                "id": str(r.id), "email": r.email, "full_name": r.full_name, "role": r.role,
            })
    result = [{"team_name": name, "members": members, "member_count": len(members)} for name, members in teams.items()]
    return {"teams": result, "count": len(result)}


@router.get("/documents")
async def list_documents(
    tenant_id: str = Query(...),
    user_id: Optional[str] = Query(None, description="Caller's real user_id, for ACL scoping"),
    limit: int = Query(50, ge=1, le=200),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real ingested-document directory, applying the exact same ACL clause
    hybrid_retriever.py already uses for retrieval — a document this caller
    isn't allowed to search over must not be listed here either, just
    because this is a different endpoint."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    caller_user_id = user_id or token.get("user_id", "")
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                SELECT d.id, d.title, d.source_app, d.resource_category, d.mime_type, d.created_at
                FROM documents d
                WHERE d.tenant_id = :t AND d.deleted_at IS NULL
                  AND (
                      (
                          NOT EXISTS (SELECT 1 FROM document_acls a WHERE a.document_id = d.id)
                          AND d.resource_group_id IS NULL
                      )
                      OR EXISTS (
                          SELECT 1 FROM document_acls a
                          WHERE a.document_id = d.id
                            AND (a.principal_type = 'domain' OR (a.principal_type = 'user' AND a.principal_external_id = :uid))
                      )
                      OR (
                          d.resource_group_id IS NOT NULL
                          AND EXISTS (
                              SELECT 1 FROM resource_group_acls g
                              WHERE g.tenant_id = d.tenant_id
                                AND g.source_app = d.source_app
                                AND g.resource_group_id = d.resource_group_id
                                AND g.principal_type = 'user'
                                AND g.principal_external_id = :uid
                          )
                      )
                  )
                ORDER BY d.created_at DESC
                LIMIT :lim
            """),
            {"t": tenant_id, "uid": caller_user_id, "lim": limit},
        )
        documents = [
            {
                "id": str(r.id), "title": r.title, "source_app": r.source_app,
                "resource_category": r.resource_category, "mime_type": r.mime_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in res.fetchall()
        ]
    return {"documents": documents, "count": len(documents)}


# ── Library (Module 6C, 2026-08-23) ──────────────────────────────────────
# A real, per-user curated subset of Documents — not a fabricated separate
# document store. Documents lists everything the caller can see; Library is
# what they've deliberately pinned. Every read re-applies the exact same ACL
# clause as /documents (and hybrid_retriever.py) rather than trusting the
# pin alone, so revoking access to a document later also drops it out of a
# user's Library automatically.

@router.post("/documents/{document_id}/pin")
async def pin_document(
    document_id: str,
    tenant_id: str = Query(...),
    user_id: Optional[str] = Query(None),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    caller_user_id = user_id or token.get("user_id", "")
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        # Real existence + ACL check before pinning — a caller can't pin a
        # document they can't already see, and pinning a nonexistent id 404s
        # instead of silently succeeding.
        acl_check = await session.execute(
            text("""
                SELECT 1 FROM documents d
                WHERE d.id = :did AND d.tenant_id = :t AND d.deleted_at IS NULL
                  AND (
                      (NOT EXISTS (SELECT 1 FROM document_acls a WHERE a.document_id = d.id) AND d.resource_group_id IS NULL)
                      OR EXISTS (SELECT 1 FROM document_acls a WHERE a.document_id = d.id
                                 AND (a.principal_type = 'domain' OR (a.principal_type = 'user' AND a.principal_external_id = :uid)))
                      OR (d.resource_group_id IS NOT NULL AND EXISTS (
                          SELECT 1 FROM resource_group_acls g
                          WHERE g.tenant_id = d.tenant_id AND g.source_app = d.source_app
                            AND g.resource_group_id = d.resource_group_id
                            AND g.principal_type = 'user' AND g.principal_external_id = :uid))
                  )
            """),
            {"did": document_id, "t": tenant_id, "uid": caller_user_id},
        )
        if acl_check.fetchone() is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Document not found or not accessible")
        await session.execute(
            text("""
                INSERT INTO document_pins (tenant_id, user_id, document_id)
                VALUES (:t, :uid, :did)
                ON CONFLICT (tenant_id, user_id, document_id) DO NOTHING
            """),
            {"t": tenant_id, "uid": caller_user_id, "did": document_id},
        )
        await session.commit()
    return {"pinned": True, "document_id": document_id}


@router.delete("/documents/{document_id}/pin")
async def unpin_document(
    document_id: str,
    tenant_id: str = Query(...),
    user_id: Optional[str] = Query(None),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    caller_user_id = user_id or token.get("user_id", "")
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("DELETE FROM document_pins WHERE tenant_id = :t AND user_id = :uid AND document_id = :did"),
            {"t": tenant_id, "uid": caller_user_id, "did": document_id},
        )
        await session.commit()
    return {"pinned": False, "document_id": document_id}


@router.get("/library")
async def list_library(
    tenant_id: str = Query(...),
    user_id: Optional[str] = Query(None),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    caller_user_id = user_id or token.get("user_id", "")
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                SELECT d.id, d.title, d.source_app, d.resource_category, d.mime_type, d.created_at, p.pinned_at
                FROM document_pins p
                JOIN documents d ON d.id = p.document_id
                WHERE p.tenant_id = :t AND p.user_id = :uid AND d.deleted_at IS NULL
                  AND (
                      (NOT EXISTS (SELECT 1 FROM document_acls a WHERE a.document_id = d.id) AND d.resource_group_id IS NULL)
                      OR EXISTS (SELECT 1 FROM document_acls a WHERE a.document_id = d.id
                                 AND (a.principal_type = 'domain' OR (a.principal_type = 'user' AND a.principal_external_id = :uid)))
                      OR (d.resource_group_id IS NOT NULL AND EXISTS (
                          SELECT 1 FROM resource_group_acls g
                          WHERE g.tenant_id = d.tenant_id AND g.source_app = d.source_app
                            AND g.resource_group_id = d.resource_group_id
                            AND g.principal_type = 'user' AND g.principal_external_id = :uid))
                  )
                ORDER BY p.pinned_at DESC
            """),
            {"t": tenant_id, "uid": caller_user_id},
        )
        library = [
            {
                "id": str(r.id), "title": r.title, "source_app": r.source_app,
                "resource_category": r.resource_category, "mime_type": r.mime_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "pinned_at": r.pinned_at.isoformat() if r.pinned_at else None,
            }
            for r in res.fetchall()
        ]
    return {"library": library, "count": len(library)}
