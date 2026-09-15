"""
Module 5 — Gateway streaming (/api/v1/stream) and async jobs (/api/v1/jobs)
real security regression suite (2026-08-22).

Before this pass, stream_router.py called the disconnected Module 4
knowledge_retrieval_client directly (no RBAC/ABAC redaction at all — that
pipeline never applies it), had no tenant-spoofing guard, and no rate
limiting. job_manager.py had the same disconnected-retrieval problem plus
no HTTP router at all (no real auth surface, no ownership check). Both are
now redirected through ConversationService.process_turn() — the same live
pipeline /api/v1/search uses — via conversation_adapter, and jobs_router.py
adds a real per-job tenant-ownership check.

Attack matrix covered: valid user, invalid/expired token, tenant A -> tenant
B, member->admin role spoofing, restricted/sensitive info redaction, revoked
API key, direct API access bypassing the UI (these endpoints ARE that
direct access).
"""
import uuid
import hashlib
import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory
from app.security.jwt_auth import jwt_engine
from tests.conftest import auth_headers_for

STREAM_URL = "/api/v1/stream"
JOBS_URL = "/api/v1/jobs"


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Stream/Jobs Sec Test {name_suffix}", "domain": f"streamjobs-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _make_mcp_key(tenant_id: str) -> str:
    raw_key = f"cbmcp_{uuid.uuid4().hex}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO mcp_api_keys (id, tenant_id, key_hash, name) VALUES (:id, :t, :h, 'stream-jobs-sec-test')"),
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


# ---------------------------------------------------------------- /stream ---

@pytest.mark.asyncio
async def test_stream_rejects_missing_credentials():
    async with await _client() as client:
        resp = await client.post(STREAM_URL, json={"query": "hello"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stream_rejects_expired_token():
    tenant_id = await _make_tenant("stream-expired")
    try:
        expired_token = jwt_engine.create_access_token(
            tenant_id=tenant_id, user_id="u1", email="e@x.com", role="admin", expires_in_seconds=-10,
        )
        async with await _client() as client:
            resp = await client.post(STREAM_URL, json={"query": "hello"}, headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_stream_rejects_tenant_a_token_claiming_tenant_b_id():
    tenant_a = await _make_tenant("stream-a")
    tenant_b = await _make_tenant("stream-b")
    try:
        headers = auth_headers_for(tenant_a, role="admin")
        async with await _client() as client:
            resp = await client.post(STREAM_URL, json={"query": "hello", "tenant_id": tenant_b}, headers=headers)
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)


@pytest.mark.asyncio
async def test_stream_succeeds_for_valid_user_and_redacts_for_member_role():
    """Valid user + restricted-content redaction: a real salary decision
    streamed back must be redacted for a member-role JWT, same as
    /api/v1/search — both now go through the same real pipeline."""
    tenant_id = await _make_tenant("stream-happy")
    decision_id = str(uuid.uuid4())
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("""
                INSERT INTO graph_decisions (id, tenant_id, decision_title, rationale, expected_outcome, actual_outcome, state, created_at)
                VALUES (:id, :t, 'Approve Q3 engineering salary increase', 'Senior engineer salary was raised 12 percent to 22 lakhs per annum.', 'Reduce attrition', 'Approved', 'completed', now())
            """), {"id": decision_id, "t": tenant_id})
            await session.commit()

        query = {"query": "By what percentage was the Q3 engineering salary increased, and to what new amount?"}
        async with await _client() as client:
            resp = await client.post(STREAM_URL, json=query, headers=auth_headers_for(tenant_id, role="member"))
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert "event: query_received" in body
        assert "event: context_finalized" in body
        assert "22 lakh" not in body.lower()
        assert "12 percent" not in body.lower() and "12%" not in body.lower()
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_stream_body_role_spoof_is_ignored():
    """member -> admin spoofing: a body-supplied role must never override the
    real JWT role."""
    tenant_id = await _make_tenant("stream-spoof")
    decision_id = str(uuid.uuid4())
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("""
                INSERT INTO graph_decisions (id, tenant_id, decision_title, rationale, expected_outcome, actual_outcome, state, created_at)
                VALUES (:id, :t, 'Approve Q3 engineering salary increase', 'Senior engineer salary was raised 12 percent to 22 lakhs per annum.', 'Reduce attrition', 'Approved', 'completed', now())
            """), {"id": decision_id, "t": tenant_id})
            await session.commit()

        headers = auth_headers_for(tenant_id, role="member")
        async with await _client() as client:
            resp = await client.post(
                STREAM_URL,
                json={"query": "By what percentage was the Q3 engineering salary increased?", "role": "admin"},
                headers=headers,
            )
        assert resp.status_code == 200
        assert "22 lakh" not in resp.text.lower()
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_stream_revoked_api_key_is_rejected():
    tenant_id = await _make_tenant("stream-revoked")
    try:
        raw_key = await _make_mcp_key(tenant_id)
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("UPDATE mcp_api_keys SET revoked_at = now() WHERE key_hash = :h"), {"h": key_hash})
            await session.commit()

        async with await _client() as client:
            resp = await client.post(STREAM_URL, json={"query": "hello"}, headers={"X-Api-Key": raw_key})
        assert resp.status_code == 401
    finally:
        await _cleanup_tenant(tenant_id)


# ----------------------------------------------------------------- /jobs ---

@pytest.mark.asyncio
async def test_jobs_rejects_missing_credentials():
    async with await _client() as client:
        resp = await client.post(JOBS_URL, json={"query": "hello"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_jobs_rejects_tenant_a_token_claiming_tenant_b_id():
    tenant_a = await _make_tenant("jobs-a")
    tenant_b = await _make_tenant("jobs-b")
    try:
        headers = auth_headers_for(tenant_a, role="admin")
        async with await _client() as client:
            resp = await client.post(JOBS_URL, json={"query": "hello", "tenant_id": tenant_b}, headers=headers)
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)


@pytest.mark.asyncio
async def test_jobs_submit_and_poll_valid_user():
    tenant_id = await _make_tenant("jobs-happy")
    try:
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            submit_resp = await client.post(JOBS_URL, json={"query": "Analyze onboarding docs"}, headers=headers)
            assert submit_resp.status_code == 200
            job_id = submit_resp.json()["job_id"]
            assert job_id.startswith("job_")

            poll_resp = await client.get(f"{JOBS_URL}/{job_id}", headers=headers)
        assert poll_resp.status_code == 200
        assert poll_resp.json()["tenant_id"] == tenant_id
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_jobs_tenant_a_cannot_poll_tenant_b_job():
    """Direct API access bypassing the UI + tenant A -> tenant B: a job_id
    submitted by tenant A must be a real 404 (not a 403 that would confirm
    the job exists) when polled with tenant B's own valid credentials."""
    tenant_a = await _make_tenant("jobs-owner-a")
    tenant_b = await _make_tenant("jobs-owner-b")
    try:
        headers_a = auth_headers_for(tenant_a, role="admin")
        headers_b = auth_headers_for(tenant_b, role="admin")
        async with await _client() as client:
            submit_resp = await client.post(JOBS_URL, json={"query": "Analyze onboarding docs"}, headers=headers_a)
            job_id = submit_resp.json()["job_id"]

            cross_resp = await client.get(f"{JOBS_URL}/{job_id}", headers=headers_b)
            missing_resp = await client.get(f"{JOBS_URL}/job_doesnotexist", headers=headers_b)
        assert cross_resp.status_code == 404
        assert missing_resp.status_code == 404
        # Both must look identical from the outside — no existence leak.
        assert cross_resp.json()["code"] == missing_resp.json()["code"] == "NOT_FOUND"
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)


@pytest.mark.asyncio
async def test_jobs_revoked_api_key_is_rejected():
    tenant_id = await _make_tenant("jobs-revoked")
    try:
        raw_key = await _make_mcp_key(tenant_id)
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("UPDATE mcp_api_keys SET revoked_at = now() WHERE key_hash = :h"), {"h": key_hash})
            await session.commit()

        async with await _client() as client:
            resp = await client.post(JOBS_URL, json={"query": "hello"}, headers={"X-Api-Key": raw_key})
        assert resp.status_code == 401
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_jobs_api_key_scoped_to_own_tenant_only():
    tenant_a = await _make_tenant("jobs-key-a")
    tenant_b = await _make_tenant("jobs-key-b")
    try:
        raw_key = await _make_mcp_key(tenant_a)
        async with await _client() as client:
            resp = await client.post(JOBS_URL, json={"query": "hello", "tenant_id": tenant_b}, headers={"X-Api-Key": raw_key})
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
