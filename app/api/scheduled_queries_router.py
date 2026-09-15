"""
Scheduled Queries API — Module 6C (2026-08-23).

Backs the real "Scheduled" panel: a saved question that re-runs itself on a
real interval, via the real in-process asyncio loop in
app/scheduler/query_scheduler.py (not Celery Beat — see that module's
docstring for why: Redis is confirmed unreachable in this environment).
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token

router = APIRouter(prefix="/api/v1/scheduled", tags=["Scheduled Queries"])

# Real, user-facing interval choices. The column itself is a plain integer
# of seconds — nothing in the schema or scheduler loop restricts it to these
# — but the UI only ever offers sensible real-world cadences.
_INTERVAL_CHOICES = {"hourly": 3600, "daily": 86400, "weekly": 604800}


class CreateScheduleRequest(BaseModel):
    tenant_id: str
    query_text: str = Field(..., min_length=1, max_length=2000)
    persona: str = "CTO"
    interval: str = Field(..., description="One of: hourly, daily, weekly")


def _row_to_dict(r) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "query_text": r.query_text,
        "persona": r.persona,
        "interval_seconds": r.interval_seconds,
        "is_active": r.is_active,
        "next_run_at": r.next_run_at.isoformat() if r.next_run_at else None,
        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
        "last_status": r.last_status,
        "last_answer": r.last_answer,
        "last_error": r.last_error,
    }


@router.post("")
async def create_schedule(req: CreateScheduleRequest, token=Depends(require_authenticated_tenant)) -> Dict[str, Any]:
    tenant_id = verify_tenant_matches_token(req.tenant_id, token)
    user_id = token.get("user_id", "")
    interval_seconds = _INTERVAL_CHOICES.get(req.interval.lower())
    if not interval_seconds:
        raise HTTPException(status_code=422, detail=f"interval must be one of {list(_INTERVAL_CHOICES)}")

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                INSERT INTO scheduled_queries (tenant_id, user_id, query_text, persona, interval_seconds, next_run_at)
                VALUES (:t, :uid, :q, :p, :interval, now())
                RETURNING id, query_text, persona, interval_seconds, is_active, next_run_at, last_run_at, last_status, last_answer, last_error
            """),
            {"t": tenant_id, "uid": user_id, "q": req.query_text.strip(), "p": req.persona, "interval": interval_seconds},
        )
        row = res.fetchone()
        await session.commit()
    return _row_to_dict(row)


@router.get("")
async def list_schedules(tenant_id: str = Query(...), token=Depends(require_authenticated_tenant)) -> Dict[str, Any]:
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    user_id = token.get("user_id", "")
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("""
                SELECT id, query_text, persona, interval_seconds, is_active, next_run_at, last_run_at, last_status, last_answer, last_error
                FROM scheduled_queries WHERE tenant_id = :t AND user_id = :uid
                ORDER BY created_at DESC
            """),
            {"t": tenant_id, "uid": user_id},
        )
        schedules = [_row_to_dict(r) for r in res.fetchall()]
    return {"schedules": schedules, "count": len(schedules)}


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str, tenant_id: str = Query(...), token=Depends(require_authenticated_tenant)) -> Dict[str, Any]:
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    user_id = token.get("user_id", "")
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("DELETE FROM scheduled_queries WHERE id = :id AND tenant_id = :t AND user_id = :uid"),
            {"id": schedule_id, "t": tenant_id, "uid": user_id},
        )
        await session.commit()
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Schedule not found.")
    return {"deleted": True, "id": schedule_id}


@router.post("/{schedule_id}/run-now")
async def run_schedule_now(schedule_id: str, tenant_id: str = Query(...), token=Depends(require_authenticated_tenant)) -> Dict[str, Any]:
    """Real immediate re-run — sets next_run_at to now() so the real
    background loop (which ticks every 10s) picks it up on its very next
    tick, instead of waiting out the real interval. Not a separate/fake
    execution path — it runs through the exact same loop as an automatic
    scheduled fire, just nudged to happen sooner."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    user_id = token.get("user_id", "")
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        res = await session.execute(
            text("UPDATE scheduled_queries SET next_run_at = now() WHERE id = :id AND tenant_id = :t AND user_id = :uid"),
            {"id": schedule_id, "t": tenant_id, "uid": user_id},
        )
        await session.commit()
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Schedule not found.")
    return {"queued": True, "id": schedule_id}
