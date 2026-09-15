"""
Master EKAP Stress & Integration Test Suite — Module 5
======================================================
Tests all 21 subsystems of Module 5 EKAP including Auth, RBAC/ABAC Policy,
Query Normalization, Response Transformers, SSE Streaming, Async Jobs, Audit Logging,
Platform Analytics, and SDK Integration.
"""
import uuid
import hashlib
import pytest
import asyncio
from sqlalchemy import text
from app.db.database import async_session_factory
from app.gateway.domain.request import SearchRequest, JobRequest
from app.gateway.domain.auth import UserIdentity
from app.gateway.authentication.auth_handler import auth_handler
from app.gateway.authorization.policy_engine import policy_engine
from app.gateway.normalization.query_normalizer import query_normalizer
from app.gateway.services.search_service import search_service
from app.gateway.transformers.markdown_transformer import markdown_transformer
from app.gateway.transformers.agent_transformer import agent_transformer, dashboard_transformer
from app.gateway.streaming.sse_streamer import sse_streamer
from app.gateway.jobs.job_manager import job_manager
from app.gateway.audit.audit_logger import audit_logger, platform_analytics
from app.gateway.events.integration.event_contracts import event_bus
from app.gateway.sdk.python_client import CompanyBrainClient
from app.gateway.common.exceptions import AuthorizationException
from app.security.jwt_auth import jwt_engine


async def _make_real_tenant(name_suffix: str) -> str:
    """Real integration (2026-08-22): search_service now delegates to
    ConversationService.process_turn() against the real, RLS-enforced DB —
    the placeholder "t1" tenant_id these tests used against the old,
    disconnected, in-memory-only Module 4 client no longer round-trips."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Gateway Stress Test {name_suffix}", "domain": f"gwstress-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _cleanup_real_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM gateway_audit_log WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM mcp_api_keys WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_ekap_authentication_and_tenant_resolution():
    """Scenario 1: Authenticates real JWT and real API-key credentials and maps tenant identity.

    Real integration (2026-08-22): AuthHandler used to check a hardcoded dict
    of 3 simulated keys ("key_tenant_alpha" etc.) — completely disconnected
    from real users/tenants. It now authenticates against the same real JWT
    engine and real mcp_api_keys table every other endpoint trusts."""
    tenant_id = await _make_real_tenant("auth")
    try:
        token = jwt_engine.create_access_token(tenant_id=tenant_id, user_id="user_alice", email="alice@x.com", role="admin")
        identity = await auth_handler.authenticate(bearer_token=token)
        assert identity.tenant_id == tenant_id
        assert identity.user_id == "user_alice"
        assert "admin" in identity.roles

        # A real, hash-only API key resolves to the same tenant, least-privilege role.
        raw_key = f"cbmcp_{uuid.uuid4().hex}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(
                text("INSERT INTO mcp_api_keys (id, tenant_id, key_hash, name) VALUES (:id, :t, :h, 'stress-test')"),
                {"id": str(uuid.uuid4()), "t": tenant_id, "h": key_hash},
            )
            await session.commit()
        key_identity = await auth_handler.authenticate(api_key=raw_key)
        assert key_identity.tenant_id == tenant_id
        assert key_identity.roles == ["member"]

        # An invalid credential MUST be rejected outright — it used to silently
        # authenticate as a caller-chosen tenant_id with no credential check at
        # all (a real auth-bypass hole, fixed 2026-08-20).
        from app.gateway.common.exceptions import AuthenticationException
        with pytest.raises(AuthenticationException):
            await auth_handler.authenticate(api_key="invalid_key")
        with pytest.raises(AuthenticationException):
            await auth_handler.authenticate(bearer_token="garbage.invalid.token")
    finally:
        await _cleanup_real_tenant(tenant_id)

@pytest.mark.asyncio
async def test_ekap_rbac_abac_payroll_authorization():
    """Scenario 2: Enforces ABAC salary restrictions based on user roles."""
    employee_id = UserIdentity(user_id="u1", tenant_id="t1", roles=["Employee"], clearance_level="Internal")
    admin_id = UserIdentity(user_id="u2", tenant_id="t1", roles=["Admin"], clearance_level="Restricted")

    # Employee querying salary should raise AuthorizationException
    with pytest.raises(AuthorizationException):
        policy_engine.authorize_request(employee_id, "Show executive salary details")

    # Admin querying salary should be authorized cleanly
    policy_engine.authorize_request(admin_id, "Show executive salary details")

@pytest.mark.asyncio
async def test_ekap_query_normalization_and_alias_resolution():
    """Scenario 3: Trims whitespace and resolves entity aliases."""
    raw_query = "   why is phoenix   delayed due to legal team?   "
    normalized, hints = query_normalizer.normalize(raw_query)

    assert normalized == "why is phoenix delayed due to legal team?"
    assert "Project Phoenix" in hints
    assert "Legal Department" in hints

@pytest.mark.asyncio
async def test_ekap_multi_format_response_transformers():
    """Scenario 4: Validates Markdown, Agent Schema, and Dashboard transformations."""
    tenant_id = await _make_real_tenant("fmt")
    try:
        identity = UserIdentity(user_id="u1", tenant_id=tenant_id, roles=["Admin"], clearance_level="Internal")

        # 1. JSON format
        req_json = SearchRequest(query="Project Phoenix milestone delay", format="json")
        res_json = await search_service.execute_search(req_json, identity, "corr_1")
        assert "query" in res_json

        # 2. Markdown format (Returns raw markdown string from search_service)
        req_md = SearchRequest(query="Project Phoenix milestone delay", format="markdown")
        res_md = await search_service.execute_search(req_md, identity, "corr_2")
        assert isinstance(res_md, str)
        assert "# Knowledge Context" in res_md

        # 3. Agent Schema format
        req_agent = SearchRequest(query="Project Phoenix milestone delay", format="agent_schema")
        res_agent = await search_service.execute_search(req_agent, identity, "corr_3")
        assert "schema_version" in res_agent
        assert "confidence_score" in res_agent
    finally:
        await _cleanup_real_tenant(tenant_id)

@pytest.mark.asyncio
async def test_ekap_sse_realtime_streaming():
    """Scenario 5: Streams pipeline execution events via Server-Sent Events (SSE)."""
    tenant_id = await _make_real_tenant("sse")
    try:
        identity = UserIdentity(user_id="u1", tenant_id=tenant_id, roles=["Employee"], clearance_level="Internal")
        req = SearchRequest(query="Project Phoenix", format="json")
        ctx_dict = await search_service.execute_search(req, identity, "corr_stream")

        # Mock KnowledgeContext for streaming generator
        from app.retrieval.domain.context import KnowledgeContext
        ctx = KnowledgeContext(**ctx_dict)

        events_captured = []
        async for chunk in sse_streamer.stream_pipeline_progress("Project Phoenix", ctx):
            events_captured.append(chunk)

        assert len(events_captured) == 5
        assert "event: query_received" in events_captured[0]
        assert "event: context_finalized" in events_captured[-1]
    finally:
        await _cleanup_real_tenant(tenant_id)

@pytest.mark.asyncio
async def test_ekap_async_job_manager_and_audit_analytics():
    """Scenario 6: Verifies async job submission, audit logging, and platform telemetry SLA metrics.

    Real integration (2026-08-22): job_manager now delegates to
    ConversationService.process_turn() (see app/gateway/jobs/job_manager.py)
    instead of the disconnected Module 4 client, so this needs a real
    tenant UUID rather than the placeholder "t1", and a realistic poll
    window — a genuine end-to-end answer (real DB + real LLM call, with
    real provider failover on quota/rate-limit errors) has taken up to ~40s
    live this session, nowhere close to the old fake pipeline's <3s."""
    tenant_id = await _make_real_tenant("job")
    try:
        job = await job_manager.submit_job(tenant_id=tenant_id, query="Analyze long-term tech stack dependencies", user_id="u1", caller_role="admin")
        assert job.job_id.startswith("job_")
        assert job.status in ["PENDING", "RUNNING"]

        # Poll for completion up to 90 seconds — a real end-to-end answer
        # involves a real DB round trip and a real LLM call chain.
        updated_job = None
        for _ in range(90):
            await asyncio.sleep(1.0)
            updated_job = job_manager.get_job(job.job_id)
            if updated_job.status in ("COMPLETED", "FAILED"):
                break

        assert updated_job.status == "COMPLETED", f"job ended in status {updated_job.status}: {updated_job.result}"
        assert updated_job.result is not None

        # Check Audit Logger & Analytics
        metrics = platform_analytics.get_metrics()
        assert metrics["total_requests"] >= 1
        assert "p95_latency_ms" in metrics
    finally:
        await _cleanup_real_tenant(tenant_id)

@pytest.mark.asyncio
async def test_ekap_python_sdk_client_integration():
    """Scenario 7: Tests CompanyBrainClient Python SDK.

    Real integration (2026-08-22): CompanyBrainClient used to build a
    UserIdentity directly from a caller-supplied tenant_id string with zero
    credential check — an in-process auth bypass. It now authenticates
    through the same real auth_handler every HTTP route uses."""
    tenant_id = await _make_real_tenant("sdk")
    try:
        token = jwt_engine.create_access_token(tenant_id=tenant_id, user_id="sdk_user", email="sdk@x.com", role="admin")
        client = CompanyBrainClient(bearer_token=token)

        # 1. SDK Search
        res = await client.search("Why is Project Phoenix delayed?", format="json")
        assert "query" in res

        # 2. SDK Markdown Search
        res_md = await client.search("Why is Project Phoenix delayed?", format="markdown")
        assert "markdown" in res_md

        # 3. SDK Async Job Submission
        job = await client.submit_async_job("Deep analysis of Project Phoenix")
        assert job.job_id.startswith("job_")

        # 4. An SDK client with no real credential must be rejected, not
        # silently default to some tenant.
        from app.gateway.common.exceptions import AuthenticationException
        bad_client = CompanyBrainClient()
        with pytest.raises(AuthenticationException):
            await bad_client.search("anything")
    finally:
        await _cleanup_real_tenant(tenant_id)
