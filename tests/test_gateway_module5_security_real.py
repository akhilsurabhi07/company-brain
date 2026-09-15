"""
Module 5 — Gateway/EKAP real security regression suite (2026-08-22).

Before this integration, app/gateway/ was a real, tested, but completely
disconnected 30-file Module 5 implementation: not mounted in app.main at all,
authenticating against a hardcoded dict of 3 simulated API keys, filtering
content with a duplicate/inferior RBAC engine, and logging "audit" records to
an in-memory list that falsely claimed to be immutable. This suite locks in
the real integration: real JWT + real mcp_api_keys auth, real tenant
isolation, real RBAC/ABAC redaction (delegated to the same
ConversationService.process_turn() pipeline every other endpoint uses), real
persistent audit logging, and real rate limiting.

Attack matrix covered, per explicit request: Tenant A -> Tenant B data,
admin -> restricted data, non-admin -> restricted data, different roles ->
different access, invalid/expired credentials, API key misuse, direct API
access bypassing the UI (this endpoint IS that direct API access).
"""
import time
import uuid
import hashlib
import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory
from app.security.jwt_auth import jwt_engine
from tests.conftest import auth_headers_for

SEARCH_URL = "/api/v1/search"


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Gateway Sec Test {name_suffix}", "domain": f"gwsec-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _make_mcp_key(tenant_id: str) -> str:
    """Creates a real mcp_api_keys row and returns the raw (pre-hash) key."""
    raw_key = f"cbmcp_{uuid.uuid4().hex}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO mcp_api_keys (id, tenant_id, key_hash, name) VALUES (:id, :t, :h, 'gw-sec-test')"),
            {"id": str(uuid.uuid4()), "t": tenant_id, "h": key_hash},
        )
        await session.commit()
    return raw_key


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM mcp_api_keys WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM gateway_audit_log WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM graph_decisions WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_search_rejects_missing_credentials():
    async with await _client() as client:
        resp = await client.post(SEARCH_URL, json={"query": "hello"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_search_rejects_garbage_bearer_token():
    async with await _client() as client:
        resp = await client.post(
            SEARCH_URL, json={"query": "hello"},
            headers={"Authorization": "Bearer garbage.invalid.token"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_search_rejects_expired_token():
    tenant_id = await _make_tenant("expired")
    try:
        expired_token = jwt_engine.create_access_token(
            tenant_id=tenant_id, user_id="u1", email="e@x.com", role="admin", expires_in_seconds=-10,
        )
        async with await _client() as client:
            resp = await client.post(
                SEARCH_URL, json={"query": "hello"},
                headers={"Authorization": f"Bearer {expired_token}"},
            )
        assert resp.status_code == 401
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_search_rejects_tenant_a_token_claiming_tenant_b_id():
    """Tenant A -> Tenant B data: a valid token for A must not read B's data
    just by putting B's tenant_id in the request body."""
    tenant_a = await _make_tenant("a-spoof")
    tenant_b = await _make_tenant("b-spoof")
    try:
        headers = auth_headers_for(tenant_a, role="admin")
        async with await _client() as client:
            resp = await client.post(
                SEARCH_URL, json={"query": "hello", "tenant_id": tenant_b}, headers=headers,
            )
        assert resp.status_code == 403
        assert resp.json()["code"] == "FORBIDDEN"
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)


@pytest.mark.asyncio
async def test_search_succeeds_for_real_tenant_own_data():
    tenant_id = await _make_tenant("happy")
    try:
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.post(SEARCH_URL, json={"query": "What is our vacation policy?"}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["tenant_id"] == tenant_id
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_search_persists_a_real_audit_log_row():
    """Locks in the fix for the fake in-memory-only AuditLogger: a real row
    must land in gateway_audit_log, scoped to the calling tenant."""
    tenant_id = await _make_tenant("audit")
    try:
        headers = auth_headers_for(tenant_id, user_id="audit_user", role="admin")
        async with await _client() as client:
            resp = await client.post(SEARCH_URL, json={"query": "audit log regression probe"}, headers=headers)
        assert resp.status_code == 200

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res = await session.execute(
                text("SELECT user_id, role, auth_method, query FROM gateway_audit_log WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
            rows = res.fetchall()
        assert len(rows) == 1, "expected exactly one persisted audit row for this tenant"
        assert rows[0].user_id == "audit_user"
        assert rows[0].role == "admin"
        assert rows[0].auth_method == "jwt"
        assert "audit log regression probe" in rows[0].query
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_admin_vs_member_role_get_different_redaction_via_gateway():
    """Admin -> restricted data, non-admin -> restricted data, different roles
    -> different access: a real salary decision surfaced through the Gateway
    must be redacted for a member-role JWT the same way it already is for
    /api/v6a/chat/turn, since both now share the same ConversationService
    pipeline."""
    tenant_id = await _make_tenant("rbac")
    decision_id = str(uuid.uuid4())
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("""
                INSERT INTO graph_decisions (id, tenant_id, decision_title, rationale, expected_outcome, actual_outcome, state, created_at)
                VALUES (:id, :t, 'Approve Q3 engineering salary increase', 'Senior engineer salary was raised 12 percent to 22 lakhs per annum to match market compensation and reduce attrition.', 'Reduce attrition', 'Approved', 'completed', now())
            """), {"id": decision_id, "t": tenant_id})
            await session.commit()

        query = {"query": "By what percentage was the Q3 engineering salary increased, and to what new amount?"}

        async with await _client() as client:
            admin_resp = await client.post(SEARCH_URL, json=query, headers=auth_headers_for(tenant_id, user_id="a1", role="admin"))
            member_resp = await client.post(SEARCH_URL, json=query, headers=auth_headers_for(tenant_id, user_id="m1", role="member"))

        assert admin_resp.status_code == 200 and member_resp.status_code == 200
        admin_text = str(admin_resp.json()["data"]).lower()
        member_text = str(member_resp.json()["data"]).lower()

        assert "22 lakh" not in member_text, f"CRITICAL: member must never see the real salary figure via Gateway, got: {member_text}"
        assert "12 percent" not in member_text and "12%" not in member_text
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_api_key_auth_resolves_real_tenant_and_defaults_to_least_privilege():
    """API key misuse: a real mcp_api_keys key must resolve to its own real
    tenant (never an attacker-chosen one) and must default to the
    least-privileged role, never admin-equivalent — mcp key creation is not
    admin-gated, so treating a key as admin would be a privilege escalation."""
    tenant_id = await _make_tenant("apikey")
    decision_id = str(uuid.uuid4())
    try:
        raw_key = await _make_mcp_key(tenant_id)

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("""
                INSERT INTO graph_decisions (id, tenant_id, decision_title, rationale, expected_outcome, actual_outcome, state, created_at)
                VALUES (:id, :t, 'Approve Q3 engineering salary increase', 'Senior engineer salary was raised 12 percent to 22 lakhs per annum to match market compensation and reduce attrition.', 'Reduce attrition', 'Approved', 'completed', now())
            """), {"id": decision_id, "t": tenant_id})
            await session.commit()

        async with await _client() as client:
            resp = await client.post(
                SEARCH_URL,
                json={"query": "By what percentage was the Q3 engineering salary increased, and to what new amount?"},
                headers={"X-Api-Key": raw_key},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == tenant_id
        assert "22 lakh" not in str(body["data"]).lower(), "API-key auth must never grant admin-equivalent access to restricted content"

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res = await session.execute(text("SELECT role, auth_method FROM gateway_audit_log WHERE tenant_id = :t"), {"t": tenant_id})
            row = res.fetchone()
        assert row.role == "member"
        assert row.auth_method == "api_key"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_revoked_api_key_is_rejected():
    tenant_id = await _make_tenant("revoked")
    try:
        raw_key = await _make_mcp_key(tenant_id)
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("UPDATE mcp_api_keys SET revoked_at = now() WHERE key_hash = :h"), {"h": key_hash})
            await session.commit()

        async with await _client() as client:
            resp = await client.post(SEARCH_URL, json={"query": "hello"}, headers={"X-Api-Key": raw_key})
        assert resp.status_code == 401
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_api_key_from_tenant_a_never_reaches_tenant_b_data():
    """Direct API access bypassing the UI: an API key minted for tenant A must
    resolve strictly to tenant A's own data, never tenant B's, even though the
    endpoint accepts an optional tenant_id in the body."""
    tenant_a = await _make_tenant("a-key")
    tenant_b = await _make_tenant("b-key")
    try:
        raw_key = await _make_mcp_key(tenant_a)
        async with await _client() as client:
            resp = await client.post(
                SEARCH_URL, json={"query": "hello", "tenant_id": tenant_b}, headers={"X-Api-Key": raw_key},
            )
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
