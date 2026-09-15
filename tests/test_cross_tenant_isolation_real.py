"""
Real test locking in cross-tenant access rejection across the main authenticated
endpoints, verified live 2026-08-22: a valid JWT for tenant A must never be usable
to read or write tenant B's data by simply changing the tenant_id in the request
body/query — verify_tenant_matches_token must reject every one of these with 403.

This was verified manually against the live server across /chat/turn,
/knowledge/graph-context, /upload/document, and /chat/feedback with no code changes
needed (all four already correctly reject); this test exists so that protection
can never silently regress.
"""
import uuid
import httpx
import pytest
from app.main import app
from tests.conftest import auth_headers_for

OTHER_TENANT = "00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_chat_turn_rejects_mismatched_tenant_id():
    my_tenant = str(uuid.uuid4())
    headers = auth_headers_for(my_tenant)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v6a/chat/turn", json={
            "tenant_id": OTHER_TENANT, "user_id": "u1", "session_id": "s1", "user_query": "hi",
        }, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_chat_stream_rejects_mismatched_tenant_id():
    my_tenant = str(uuid.uuid4())
    headers = auth_headers_for(my_tenant)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v6a/chat/stream", json={
            "tenant_id": OTHER_TENANT, "user_id": "u1", "session_id": "s1", "user_query": "hi",
        }, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_graph_context_rejects_mismatched_tenant_id():
    my_tenant = str(uuid.uuid4())
    headers = auth_headers_for(my_tenant)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/knowledge/graph-context?tenant_id={OTHER_TENANT}&query=test", headers=headers
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_upload_rejects_mismatched_tenant_id():
    my_tenant = str(uuid.uuid4())
    headers = auth_headers_for(my_tenant)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/upload/document",
            files={"file": ("x.txt", b"hello", "text/plain")},
            data={"tenant_id": OTHER_TENANT, "source_label": "UPLOAD"},
            headers=headers,
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_feedback_rejects_mismatched_tenant_id():
    my_tenant = str(uuid.uuid4())
    headers = auth_headers_for(my_tenant)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v6a/chat/feedback", json={
            "task_id": "turn_fake", "tenant_id": OTHER_TENANT, "feedback": "up", "comment": "",
        }, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_chat_turn_rejects_invalid_token():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v6a/chat/turn", json={
            "tenant_id": OTHER_TENANT, "user_id": "u1", "session_id": "s1", "user_query": "hi",
        }, headers={"Authorization": "Bearer garbage.invalid.token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_chat_turn_rejects_missing_token():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v6a/chat/turn", json={
            "tenant_id": OTHER_TENANT, "user_id": "u1", "session_id": "s1", "user_query": "hi",
        })
    assert resp.status_code == 401
