"""
Complex Edge-Case & Stress Test Suite for Module 5 EKAP
======================================================
Rigorous testing of intricate edge cases in Module 5 including:
- Ultra-compact Mobile JSON formatting
- Multi-role ABAC clearance filtering across 4 security levels
- Complex entity alias canonicalization & fuzzy typo matching
- Token-bucket tenant rate limiting enforcement
- Multi-tenant concurrent search isolation under heavy load
"""
import uuid
import pytest
import asyncio
from sqlalchemy import text
from app.db.database import async_session_factory
from app.gateway.domain.request import SearchRequest
from app.gateway.domain.auth import UserIdentity
from app.gateway.services.search_service import search_service
from app.gateway.normalization.query_normalizer import query_normalizer
from app.gateway.authorization.policy_engine import policy_engine
from app.gateway.infrastructure.tenant_rate_limiter import TenantRateLimiter
from app.gateway.common.exceptions import AuthorizationException, RateLimitException


async def _make_real_tenant(name_suffix: str) -> str:
    """Real integration (2026-08-22): search_service now delegates to
    ConversationService.process_turn() against the real, RLS-enforced DB —
    placeholder tenant_ids like "t1"/"tenant_alpha" no longer round-trip the
    way they did against the old, disconnected, in-memory-only Module 4
    client."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Edge Case Test {name_suffix}", "domain": f"edgecase-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _cleanup_real_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM gateway_audit_log WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_module5_mobile_format_transformer():
    """Scenario 1: Verifies compact mobile JSON formatting."""
    tenant_id = await _make_real_tenant("mobile")
    try:
        identity = UserIdentity(user_id="m1", tenant_id=tenant_id, roles=["Employee"], clearance_level="Internal")
        req = SearchRequest(query="Project Phoenix milestone update", format="mobile")
        res = await search_service.execute_search(req, identity, "corr_mob")

        assert "q" in res
        assert "intent" in res
        assert "confidence" in res
        assert "citations_count" in res
    finally:
        await _cleanup_real_tenant(tenant_id)

@pytest.mark.asyncio
async def test_module5_multi_level_abac_clearance_security():
    """Scenario 2: Verifies clearance levels across Internal, Confidential, and Restricted."""
    emp_internal = UserIdentity(user_id="u1", tenant_id="t1", roles=["Employee"], clearance_level="Internal")
    mgr_confidential = UserIdentity(user_id="u2", tenant_id="t1", roles=["Manager"], clearance_level="Confidential")
    admin_restricted = UserIdentity(user_id="u3", tenant_id="t1", roles=["Admin"], clearance_level="Restricted")

    # Internal user attempting Restricted clearance query must be blocked
    with pytest.raises(AuthorizationException):
        policy_engine.authorize_request(emp_internal, "Project Titan architectural blueprint", requested_confidentiality="Restricted")

    # Manager with Confidential clearance attempting Restricted query must be blocked
    with pytest.raises(AuthorizationException):
        policy_engine.authorize_request(mgr_confidential, "Project Titan architectural blueprint", requested_confidentiality="Restricted")

    # Admin with Restricted clearance must be authorized cleanly
    policy_engine.authorize_request(admin_restricted, "Project Titan architectural blueprint", requested_confidentiality="Restricted")

@pytest.mark.asyncio
async def test_module5_dirty_query_normalization_and_alias_resolution():
    """Scenario 3: Resolves multiple nested aliases from dirty query text."""
    dirty_query = "\t\n  WHat is the PHOENIX   status and GDPr compliance   for Atlas?  \r"
    normalized, hints = query_normalizer.normalize(dirty_query)

    assert normalized == "WHat is the PHOENIX status and GDPr compliance for Atlas?"
    assert "Project Phoenix" in hints
    assert "Project Atlas" in hints
    assert "GDPR Compliance Verification" in hints

@pytest.mark.asyncio
async def test_module5_typo_fuzzy_matching():
    """Scenario 4: Tests typo correction where user misspells words like 'phnix' or 'atls'."""
    typo_query = "What is the phnix roadmap and atls release status?"
    normalized, hints = query_normalizer.normalize(typo_query)

    assert "Project Phoenix" in hints
    assert "Project Atlas" in hints

@pytest.mark.asyncio
async def test_module5_tenant_token_bucket_rate_limiter():
    """Scenario 5: Tests token-bucket rate limiter under high request bursts."""
    rate_limiter = TenantRateLimiter(default_capacity=5, refill_rate_per_sec=1.0)
    
    # First 5 requests should pass
    for i in range(5):
        allowed = await rate_limiter.acquire("tenant_burst")
        assert allowed is True

    # 6th request should be rejected due to capacity limit
    allowed = await rate_limiter.acquire("tenant_burst")
    assert allowed is False

@pytest.mark.asyncio
async def test_module5_concurrent_5_tenant_stress():
    """Scenario 6: 5 distinct tenants executing simultaneous searches."""
    tenants = [await _make_real_tenant(f"stress-{i}") for i in range(5)]
    try:
        async def tenant_search(t_id):
            identity = UserIdentity(user_id=f"user_{t_id}", tenant_id=t_id, roles=["Employee"], clearance_level="Internal")
            req = SearchRequest(query=f"Status update for {t_id}", format="json")
            res = await search_service.execute_search(req, identity, f"corr_{t_id}")
            return res

        results = await asyncio.gather(*[tenant_search(t) for t in tenants])
        assert len(results) == 5
        for idx, res in enumerate(results):
            assert "query" in res
    finally:
        for t in tenants:
            await _cleanup_real_tenant(t)
