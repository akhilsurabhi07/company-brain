"""
Real test for a bug found via live testing 2026-08-22: POST /api/v6a/chat/feedback
returned "Feedback recorded" but only ever wrote a transient logger.info() line —
no table existed to store it in at all. Every real thumbs up/down a user submitted
vanished the moment that log line rotated or the process restarted, despite the API
telling the user it was durably saved — the exact "fake success" anti-pattern
already fixed multiple times this session for UI buttons, this time in a real
backend API. Fixed by genuinely persisting to a new chat_feedback table.
"""
import uuid
import httpx
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.main import app
from tests.conftest import auth_headers_for


@pytest.mark.asyncio
async def test_feedback_is_actually_persisted_in_the_database():
    tenant_id = str(uuid.uuid4())
    headers = auth_headers_for(tenant_id)
    turn_id = "turn_" + uuid.uuid4().hex[:10]

    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Feedback Persist Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "domain": f"feedbacktest-{tenant_id[:8]}.example.com"},
        )
        await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v6a/chat/feedback", json={
            "task_id": turn_id, "tenant_id": tenant_id, "feedback": "up", "comment": "great answer",
        }, headers=headers)
    assert resp.status_code == 200
    assert resp.json().get("status") == "success"

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            row = (await session.execute(
                text("SELECT feedback, comment, turn_id FROM chat_feedback WHERE tenant_id = :t AND turn_id = :turn"),
                {"t": tenant_id, "turn": turn_id},
            )).fetchone()
        assert row is not None, "feedback must genuinely be persisted, not just logged"
        assert row.feedback == "up"
        assert row.comment == "great answer"
        assert row.turn_id == turn_id
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("DELETE FROM chat_feedback WHERE tenant_id = :t"), {"t": tenant_id})
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
            await session.commit()
