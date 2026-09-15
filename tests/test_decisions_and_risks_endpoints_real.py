"""
Module 6B — real Decisions & Risks sidebar panels (2026-08-22).

Before this, graph_decisions and graph_conflicts were real, populated tables
with no read endpoint anywhere — the sidebar's "Decisions"/"Risks" nav items
were honestly marked "Soon" rather than faked. This adds the first real read
path, reusing the same sentence-level RBAC redaction already proven correct
for decisions surfaced through chat (app.security.content_redaction).
"""
import uuid
import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory
from tests.conftest import auth_headers_for

DECISIONS_URL = "/api/v1/knowledge/decisions"
RISKS_URL = "/api/v1/knowledge/risks"


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Decisions Risks Test {name_suffix}", "domain": f"decrisk-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM graph_decisions WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM graph_conflicts WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_decisions_list_redacts_restricted_content_for_member_not_admin():
    tenant_id = await _make_tenant("dec")
    decision_id = str(uuid.uuid4())
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("""
                INSERT INTO graph_decisions (id, tenant_id, decision_title, rationale, expected_outcome, actual_outcome, state, created_at)
                VALUES (:id, :t, 'Approve Q3 engineering salary increase', 'Senior engineer salary was raised 12 percent to 22 lakhs per annum.', 'Reduce attrition', 'Approved', 'completed', now())
            """), {"id": decision_id, "t": tenant_id})
            await session.commit()

        async with await _client() as client:
            admin_resp = await client.get(DECISIONS_URL, params={"tenant_id": tenant_id}, headers=auth_headers_for(tenant_id, role="admin"))
            member_resp = await client.get(DECISIONS_URL, params={"tenant_id": tenant_id}, headers=auth_headers_for(tenant_id, role="member"))

        assert admin_resp.status_code == 200 and member_resp.status_code == 200
        admin_body = admin_resp.json()
        member_body = member_resp.json()
        assert admin_body["count"] == 1
        assert "22 lakh" in admin_body["decisions"][0]["rationale"].lower()
        # The decision itself must still be visible to a member (title/state) —
        # a member should be able to see "a decision was made here" without
        # seeing the restricted figures, not have the whole record vanish.
        assert member_body["count"] == 1
        assert member_body["decisions"][0]["title"] == "Approve Q3 engineering salary increase"
        assert "22 lakh" not in member_body["decisions"][0]["rationale"].lower()
        assert "withheld" in member_body["decisions"][0]["rationale"].lower()
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_risks_list_returns_real_conflicts():
    tenant_id = await _make_tenant("risk")
    conflict_id = str(uuid.uuid4())
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("""
                INSERT INTO graph_conflicts (id, tenant_id, conflict_type, description, evidence_a_json, evidence_b_json, severity, resolution_status, created_at)
                VALUES (:id, :t, 'data_disagreement', 'Probation period disagreement: HR policy says 90 days, offer letter template says 180 days.', '{}', '{}', 'high', 'open', now())
            """), {"id": conflict_id, "t": tenant_id})
            await session.commit()

        async with await _client() as client:
            resp = await client.get(RISKS_URL, params={"tenant_id": tenant_id}, headers=auth_headers_for(tenant_id, role="admin"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["risks"][0]["severity"] == "high"
        assert "90 days" in body["risks"][0]["description"].lower()
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_decisions_and_risks_are_tenant_isolated():
    tenant_a = await _make_tenant("iso-a")
    tenant_b = await _make_tenant("iso-b")
    decision_id = str(uuid.uuid4())
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_a})
            await session.execute(text("""
                INSERT INTO graph_decisions (id, tenant_id, decision_title, rationale, state, created_at)
                VALUES (:id, :t, 'Tenant A only decision', 'Some rationale.', 'completed', now())
            """), {"id": decision_id, "t": tenant_a})
            await session.commit()

        async with await _client() as client:
            resp = await client.get(DECISIONS_URL, params={"tenant_id": tenant_b}, headers=auth_headers_for(tenant_b, role="admin"))
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)


@pytest.mark.asyncio
async def test_decisions_rejects_cross_tenant_token():
    tenant_a = await _make_tenant("cross-a")
    tenant_b = await _make_tenant("cross-b")
    try:
        headers = auth_headers_for(tenant_a, role="admin")
        async with await _client() as client:
            resp = await client.get(DECISIONS_URL, params={"tenant_id": tenant_b}, headers=headers)
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
