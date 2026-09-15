"""
Admin Dashboard — Module 6C (2026-08-23).

Real bug found+fixed the same session: frontend/admin.html already existed
(324 lines, real /upload/stats-backed stat cards) but sent no Authorization
header on any request and was never linked from the main app's nav — a
fourth instance of this engagement's "real code, not actually reachable"
pattern. Fixed admin.html's auth handling + linked it in, and added the one
genuinely missing real capability: team/role management, backed by
app/api/admin_router.py.
"""
import uuid
import bcrypt
import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory
from tests.conftest import auth_headers_for

USERS_URL = "/api/v1/admin/users"
ACTIVITY_URL = "/api/v1/admin/activity"


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Admin Dash Test {name_suffix}", "domain": f"admindash-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _make_user(tenant_id: str, email: str, full_name: str, role: str) -> str:
    user_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("""
                INSERT INTO users (id, tenant_id, email, hashed_password, full_name, role)
                VALUES (:id, :t, :email, :pw, :name, :role)
            """),
            {"id": user_id, "t": tenant_id, "email": email, "pw": bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
             "name": full_name, "role": role},
        )
        await session.commit()
    return user_id


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM ingestion_audit_logs WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_admin_lists_real_users_with_roles():
    tenant_id = await _make_tenant("list")
    try:
        await _make_user(tenant_id, "eng@example.com", "Eng Person", "member")
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.get(USERS_URL, params={"tenant_id": tenant_id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["users"][0]["role"] == "member"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_non_admin_cannot_list_users():
    tenant_id = await _make_tenant("nonadmin")
    try:
        headers = auth_headers_for(tenant_id, role="member")
        async with await _client() as client:
            resp = await client.get(USERS_URL, params={"tenant_id": tenant_id}, headers=headers)
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_admin_can_change_a_members_role_to_admin():
    tenant_id = await _make_tenant("promote")
    try:
        member_id = await _make_user(tenant_id, "promote_me@example.com", "Promote Me", "member")
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.patch(
                f"{USERS_URL}/{member_id}/role", params={"tenant_id": tenant_id, "role": "admin"}, headers=headers
            )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_cannot_demote_the_last_remaining_admin():
    """A real safety guard: demoting a tenant's only admin would lock the
    workspace out of ever managing itself again."""
    tenant_id = await _make_tenant("lastadmin")
    try:
        admin_id = await _make_user(tenant_id, "only_admin@example.com", "Only Admin", "admin")
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.patch(
                f"{USERS_URL}/{admin_id}/role", params={"tenant_id": tenant_id, "role": "member"}, headers=headers
            )
        assert resp.status_code == 409
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_demoting_one_of_two_admins_is_allowed():
    tenant_id = await _make_tenant("twoadmins")
    try:
        admin_a = await _make_user(tenant_id, "admin_a@example.com", "Admin A", "admin")
        await _make_user(tenant_id, "admin_b@example.com", "Admin B", "admin")
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.patch(
                f"{USERS_URL}/{admin_a}/role", params={"tenant_id": tenant_id, "role": "member"}, headers=headers
            )
        assert resp.status_code == 200
        assert resp.json()["role"] == "member"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_role_update_rejects_an_unknown_role_value():
    tenant_id = await _make_tenant("badrole")
    try:
        user_id = await _make_user(tenant_id, "someone@example.com", "Someone", "member")
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.patch(
                f"{USERS_URL}/{user_id}/role", params={"tenant_id": tenant_id, "role": "superuser"}, headers=headers
            )
        assert resp.status_code == 422
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_activity_log_starts_empty_and_is_admin_gated():
    tenant_id = await _make_tenant("activity")
    try:
        admin_headers = auth_headers_for(tenant_id, role="admin")
        member_headers = auth_headers_for(tenant_id, role="member")
        async with await _client() as client:
            admin_resp = await client.get(ACTIVITY_URL, params={"tenant_id": tenant_id}, headers=admin_headers)
            member_resp = await client.get(ACTIVITY_URL, params={"tenant_id": tenant_id}, headers=member_headers)
        assert admin_resp.status_code == 200
        assert admin_resp.json()["count"] == 0  # honest — nothing uploaded yet
        assert member_resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_admin_users_rejects_cross_tenant_token():
    tenant_a = await _make_tenant("cross-a")
    tenant_b = await _make_tenant("cross-b")
    try:
        headers = auth_headers_for(tenant_a, role="admin")
        async with await _client() as client:
            resp = await client.get(USERS_URL, params={"tenant_id": tenant_b}, headers=headers)
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
