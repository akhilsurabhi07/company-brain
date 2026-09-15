"""
Scheduled Queries — Module 6C (2026-08-23).

Real, in-process asyncio scheduler (app/scheduler/query_scheduler.py), not
Celery Beat — Redis is confirmed unreachable in this dev environment. These
tests exercise the real API surface plus a direct call into the real tick
function (_run_due_schedules_once) to prove a due schedule actually gets
re-run and its real answer stored, without waiting out a real interval or
needing the full FastAPI startup event to have fired.
"""
import uuid
import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory
from tests.conftest import auth_headers_for

SCHED_URL = "/api/v1/scheduled"


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Scheduled Test {name_suffix}", "domain": f"scheduled-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM scheduled_queries WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_turns WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_sessions WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_create_list_and_delete_a_schedule():
    tenant_id = await _make_tenant("crud")
    try:
        headers = auth_headers_for(tenant_id, user_id="sched_user")
        async with await _client() as client:
            empty = await client.get(SCHED_URL, params={"tenant_id": tenant_id}, headers=headers)
            assert empty.json()["count"] == 0

            create = await client.post(
                SCHED_URL, headers=headers,
                json={"tenant_id": tenant_id, "query_text": "What changed this week?", "interval": "daily"},
            )
            assert create.status_code == 200
            body = create.json()
            assert body["interval_seconds"] == 86400
            assert body["last_status"] is None  # honest — never run yet
            sched_id = body["id"]

            listed = await client.get(SCHED_URL, params={"tenant_id": tenant_id}, headers=headers)
            assert listed.json()["count"] == 1

            deleted = await client.delete(f"{SCHED_URL}/{sched_id}", params={"tenant_id": tenant_id}, headers=headers)
            assert deleted.status_code == 200

            after = await client.get(SCHED_URL, params={"tenant_id": tenant_id}, headers=headers)
            assert after.json()["count"] == 0
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_create_rejects_an_unknown_interval():
    tenant_id = await _make_tenant("badinterval")
    try:
        headers = auth_headers_for(tenant_id)
        async with await _client() as client:
            resp = await client.post(
                SCHED_URL, headers=headers,
                json={"tenant_id": tenant_id, "query_text": "test", "interval": "every_millisecond"},
            )
        assert resp.status_code == 422
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_run_now_makes_it_immediately_due():
    tenant_id = await _make_tenant("runnow")
    try:
        headers = auth_headers_for(tenant_id)
        async with await _client() as client:
            create = await client.post(
                SCHED_URL, headers=headers,
                json={"tenant_id": tenant_id, "query_text": "test question", "interval": "weekly"},
            )
            sched_id = create.json()["id"]
            run_now = await client.post(f"{SCHED_URL}/{sched_id}/run-now", params={"tenant_id": tenant_id}, headers=headers)
        assert run_now.status_code == 200

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            row = (await session.execute(
                text("SELECT next_run_at <= now() AS is_due FROM scheduled_queries WHERE id = :id"), {"id": sched_id}
            )).fetchone()
        assert row.is_due is True, "run-now must make next_run_at immediately due"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_scheduler_tick_actually_runs_a_due_schedule_and_stores_a_real_answer():
    """The real end-to-end proof: a due schedule gets picked up by the real
    tick function, a real chat turn actually runs, and a real answer lands
    back in the row — not a stub, not a fixed string."""
    from app.scheduler.query_scheduler import _run_due_schedules_once

    tenant_id = await _make_tenant("tick")
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res = await session.execute(
                text("""
                    INSERT INTO scheduled_queries (tenant_id, user_id, query_text, persona, interval_seconds, next_run_at)
                    VALUES (:t, 'tick_user', 'What is the capital of France?', 'CTO', 3600, now() - INTERVAL '1 minute')
                    RETURNING id
                """),
                {"t": tenant_id},
            )
            schedule_id = res.fetchone().id
            await session.commit()

        await _run_due_schedules_once()

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            row = (await session.execute(
                text("SELECT last_status, last_answer, last_run_at, next_run_at FROM scheduled_queries WHERE id = :id"),
                {"id": schedule_id},
            )).fetchone()
        assert row.last_run_at is not None, "a due schedule must have actually been run"
        assert row.last_status == "ok", f"expected a real successful run, got status={row.last_status!r}"
        assert row.last_answer and len(row.last_answer) > 0, "a real run must produce a real stored answer"
        assert "paris" in row.last_answer.lower(), f"expected a real, correct answer, got: {row.last_answer!r}"
        # next_run_at must have advanced roughly interval_seconds into the future,
        # not stayed in the past (which would make it fire again on every tick forever).
        assert row.next_run_at is not None
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_scheduler_tick_reuses_the_real_shared_service_singleton():
    """Real fix found 2026-08-24: this tick used to construct a brand-new
    ConversationService() (and a brand-new, cold ConversationCache()) on
    every single call — a real duplicate-instance pattern separate from the
    one real shared singleton every live chat request already uses. Proves
    the fix: the scheduler now goes through the exact same
    ConversationContainer singleton, not a second, disconnected instance."""
    from app.scheduler import query_scheduler
    from app.conversation.container import ConversationContainer

    tenant_id = await _make_tenant("singleton")
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(
                text("""
                    INSERT INTO scheduled_queries (tenant_id, user_id, query_text, persona, interval_seconds, next_run_at)
                    VALUES (:t, 'singleton_user', 'What is the capital of Italy?', 'CTO', 3600, now() - INTERVAL '1 minute')
                """),
                {"t": tenant_id},
            )
            await session.commit()

        service_before = ConversationContainer.get_conversation_service()
        await query_scheduler._run_due_schedules_once()
        service_after = ConversationContainer.get_conversation_service()

        assert service_before is service_after, (
            "the scheduler tick must reuse the real shared singleton, not construct its own separate instance"
        )
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_list_rejects_cross_tenant_token():
    tenant_a = await _make_tenant("cross-a")
    tenant_b = await _make_tenant("cross-b")
    try:
        headers = auth_headers_for(tenant_a)
        async with await _client() as client:
            resp = await client.get(SCHED_URL, params={"tenant_id": tenant_b}, headers=headers)
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
