"""
Real test for a bug found via live testing 2026-08-21: the SSE `/stream` endpoint's
final "done" event never carried the real turn_id, so the frontend generated a fake
client-side "msg_<timestamp>" id for every message and submitted feedback (thumbs
up/down) against that fake id — real user feedback had zero relationship to the
actual conversation turn it was about. Fixed by including the real turn_id (already
returned by process_turn) in the "done" event payload.

While adding this test, found a SECOND, much more severe bug in the same endpoint:
the streaming loop's per-word variable was also named `token` — an accidental
naming collision with the outer function's `token=Depends(require_authenticated_
tenant)` JWT parameter. Because the nested `generate()` closure assigns to `token`
anywhere in its body, Python treats `token` as local to the whole closure, so the
earlier, legitimate read of the real JWT (`token.get("role", "admin")`) raised
"cannot access local variable 'token' where it is not associated with a value" —
confirmed live: EVERY real /stream call (the frontend's primary chat path) was
returning an "error" SSE event with exactly this message instead of a real answer.
"""
import json
import uuid
import httpx
import pytest
from sqlalchemy import text
from app.main import app
from app.db.database import async_session_factory
from tests.conftest import auth_headers_for


async def _make_tenant(name_suffix: str) -> str:
    """Real integration (2026-08-22): ConversationService now persists
    sessions/turns to real, RLS-protected Postgres tables
    (conversation_sessions/conversation_turns), each with a real FK to
    tenants(id) — a random, never-registered tenant_id (fine against the old
    in-memory-only session repository) now fails with a real foreign key
    violation instead of silently succeeding."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Stream Turn ID Test {name_suffix}", "domain": f"streamturnid-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_turns WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_sessions WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_stream_never_returns_the_token_scoping_error():
    """Direct regression lock for the critical bug above: a real /stream call must
    never surface an "error" event, and specifically never this exact scoping
    message, for an ordinary valid request."""
    tenant_id = await _make_tenant("scoping")
    try:
        headers = auth_headers_for(tenant_id)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream(
                "POST", "/api/v6a/chat/stream",
                json={
                    "user_query": "what is the capital of Japan",
                    "session_id": "stream-scoping-bug-test",
                    "tenant_id": tenant_id,
                    "user_id": "stream_test_user",
                },
                headers=headers,
            ) as resp:
                assert resp.status_code == 200
                saw_done = False
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    evt = json.loads(line[6:])
                    assert evt.get("type") != "error", f"stream must not error on a normal request, got: {evt}"
                    if evt.get("type") == "done":
                        saw_done = True
        assert saw_done, "a normal request must reach a real 'done' event"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_stream_done_event_carries_a_real_turn_id():
    tenant_id = await _make_tenant("turnid")
    try:
        headers = auth_headers_for(tenant_id)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream(
                "POST", "/api/v6a/chat/stream",
                json={
                    "user_query": "what is the capital of France",
                    "session_id": "stream-turnid-test",
                    "tenant_id": tenant_id,
                    "user_id": "stream_test_user",
                },
                headers=headers,
            ) as resp:
                assert resp.status_code == 200
                done_event = None
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    evt = json.loads(line[6:])
                    if evt.get("type") == "done":
                        done_event = evt
                        break
    finally:
        await _cleanup_tenant(tenant_id)

    assert done_event is not None, "stream must emit a 'done' event"
    assert done_event.get("turn_id"), (
        "the 'done' event must carry a real turn_id — without it, feedback "
        "submitted from the UI can't be attributed to the real conversation turn"
    )
    assert done_event["turn_id"] not in ("acknowledgement", "greeting", "builtin-kb"), (
        "a real conversational query must produce a real turn_id, not one of the "
        "fixed fast-path sentinel values"
    )
