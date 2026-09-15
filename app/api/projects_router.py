"""
Projects API — Module 6B (2026-08-22).

Real, minimal "Project memory" foundation: a project is a named container a
user can group conversations under. Before this, "Projects" was an honestly
disabled "Soon" sidebar button with no backend concept at all. This is a
genuine MVP, not the vision's full scope (conversations/decisions/docs/
artifacts/architecture/people/meetings/risks/tasks/code/timeline per
project) — it wires projects <-> conversation_sessions, which is the piece
everything else would attach to next.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token

router = APIRouter(prefix="/api/v1/projects", tags=["Projects"])


class CreateProjectRequest(BaseModel):
    tenant_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


@router.post("")
async def create_project(req: CreateProjectRequest, token=Depends(require_authenticated_tenant)) -> Dict[str, Any]:
    tenant_id = verify_tenant_matches_token(req.tenant_id, token)
    user_id = token.get("user_id", "unknown_user")
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                INSERT INTO projects (tenant_id, name, description, created_by)
                VALUES (:t, :name, :desc, :by)
                RETURNING id, name, description, created_by, created_at
            """),
            {"t": tenant_id, "name": req.name, "desc": req.description, "by": user_id},
        )
        row = res.fetchone()
        await session.commit()
    return {
        "id": str(row.id), "name": row.name, "description": row.description,
        "created_by": row.created_by, "created_at": row.created_at.isoformat(),
    }


@router.get("")
async def list_projects(
    tenant_id: str = Query(...),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                SELECT p.id, p.name, p.description, p.created_at,
                       (SELECT COUNT(*) FROM conversation_sessions cs WHERE cs.project_id = p.id) AS session_count
                FROM projects p WHERE p.tenant_id = :t ORDER BY p.updated_at DESC
            """),
            {"t": tenant_id},
        )
        projects = [
            {
                "id": str(r.id), "name": r.name, "description": r.description,
                "created_at": r.created_at.isoformat(), "session_count": r.session_count,
            }
            for r in res.fetchall()
        ]
    return {"projects": projects, "count": len(projects)}


@router.get("/{project_id}/sessions")
async def list_project_sessions(
    project_id: str,
    tenant_id: str = Query(...),
    token=Depends(require_authenticated_tenant),
) -> Dict[str, Any]:
    """Real project memory read path: every conversation ever assigned to
    this project, oldest activity last — the "revisitable months later"
    part of the vision, now backed by a durable table instead of nothing."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                SELECT session_id, title, state, pinned, created_at, updated_at
                FROM conversation_sessions
                WHERE tenant_id = :t AND project_id = :pid
                ORDER BY updated_at DESC
            """),
            {"t": tenant_id, "pid": project_id},
        )
        sessions = [
            {
                "session_id": r.session_id, "title": r.title, "state": r.state, "pinned": r.pinned,
                "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
            }
            for r in res.fetchall()
        ]
    return {"sessions": sessions, "count": len(sessions)}


class AssignSessionRequest(BaseModel):
    tenant_id: str
    session_id: str
    project_id: Optional[str] = None  # null = remove from any project


@router.post("/assign-session")
async def assign_session_to_project(req: AssignSessionRequest, token=Depends(require_authenticated_tenant)) -> Dict[str, Any]:
    """Moves a conversation into (or out of, with project_id=null) a
    project. A session and the project it's assigned to must belong to the
    same real, authenticated tenant — the UPDATE's own WHERE clause plus RLS
    both enforce that, so a project_id from another tenant simply matches
    zero rows rather than silently relinking someone else's conversation."""
    tenant_id = verify_tenant_matches_token(req.tenant_id, token)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                UPDATE conversation_sessions SET project_id = :pid, updated_at = now()
                WHERE session_id = :sid AND tenant_id = :t
                RETURNING session_id
            """),
            {"pid": req.project_id, "sid": req.session_id, "t": tenant_id},
        )
        updated = res.fetchone()
        await session.commit()
    if not updated:
        return {"status": "not_found"}
    return {"status": "success", "session_id": req.session_id, "project_id": req.project_id}
