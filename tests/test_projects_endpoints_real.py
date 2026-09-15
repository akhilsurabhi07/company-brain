"""
Module 6B — real Projects API (2026-08-22).

Before this, "Projects" was an honestly disabled "Soon" sidebar button with
zero backend concept. This is a real, minimal MVP: create a project, list a
tenant's projects, assign a conversation session to one, and list a
project's sessions back — the "project memory... revisitable months later"
foundation everything else (decisions/docs/artifacts scoped to a project)
would build on next.
"""
import uuid
import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory
from app.conversation.session.postgres_repo import PostgresSessionRepository
from app.conversation.domain.context import ConversationSession
from app.conversation.domain.states import SessionState
from tests.conftest import auth_headers_for

PROJECTS_URL = "/api/v1/projects"


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Projects Test {name_suffix}", "domain": f"projtest-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_turns WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_sessions WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM projects WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_create_and_list_project():
    tenant_id = await _make_tenant("crud")
    try:
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            create_resp = await client.post(PROJECTS_URL, json={
                "tenant_id": tenant_id, "name": "Q4 Onboarding Revamp", "description": "Real project test",
            }, headers=headers)
            assert create_resp.status_code == 200
            project_id = create_resp.json()["id"]

            list_resp = await client.get(PROJECTS_URL, params={"tenant_id": tenant_id}, headers=headers)
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert body["count"] == 1
        assert body["projects"][0]["id"] == project_id
        assert body["projects"][0]["name"] == "Q4 Onboarding Revamp"
        assert body["projects"][0]["session_count"] == 0
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_assign_session_to_project_and_list_back():
    tenant_id = await _make_tenant("assign")
    try:
        # Real conversation session via the real repository (not a fixture row).
        repo = PostgresSessionRepository()
        session_obj = ConversationSession(tenant_id=tenant_id, user_id="u1", title="Real conversation")
        session_obj.state = SessionState.ACTIVE
        await repo.create_session(session_obj)

        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            create_resp = await client.post(PROJECTS_URL, json={"tenant_id": tenant_id, "name": "Real Project"}, headers=headers)
            project_id = create_resp.json()["id"]

            assign_resp = await client.post(f"{PROJECTS_URL}/assign-session", json={
                "tenant_id": tenant_id, "session_id": session_obj.session_id, "project_id": project_id,
            }, headers=headers)
            assert assign_resp.status_code == 200
            assert assign_resp.json()["status"] == "success"

            sessions_resp = await client.get(f"{PROJECTS_URL}/{project_id}/sessions", params={"tenant_id": tenant_id}, headers=headers)
        assert sessions_resp.status_code == 200
        body = sessions_resp.json()
        assert body["count"] == 1
        assert body["sessions"][0]["session_id"] == session_obj.session_id
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_projects_are_tenant_isolated():
    tenant_a = await _make_tenant("iso-a")
    tenant_b = await _make_tenant("iso-b")
    try:
        headers_a = auth_headers_for(tenant_a, role="admin")
        headers_b = auth_headers_for(tenant_b, role="admin")
        async with await _client() as client:
            await client.post(PROJECTS_URL, json={"tenant_id": tenant_a, "name": "Tenant A Only"}, headers=headers_a)
            list_resp = await client.get(PROJECTS_URL, params={"tenant_id": tenant_b}, headers=headers_b)
        assert list_resp.status_code == 200
        assert list_resp.json()["count"] == 0
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)


@pytest.mark.asyncio
async def test_create_project_rejects_cross_tenant_token():
    tenant_a = await _make_tenant("cross-a")
    tenant_b = await _make_tenant("cross-b")
    try:
        headers = auth_headers_for(tenant_a, role="admin")
        async with await _client() as client:
            resp = await client.post(PROJECTS_URL, json={"tenant_id": tenant_b, "name": "Should be rejected"}, headers=headers)
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
