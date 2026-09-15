"""
Ultra-Complex Fuzzy Typo, Phonetic Shorthand & 20-Request Concurrent Stress Suite
====================================================================================
Verifies advanced typo resilience, phonetic shorthands, ABAC security guardrails,
and high-concurrency 20-tenant multi-format search execution across EKAP.
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
from app.gateway.common.exceptions import AuthorizationException


async def _make_real_tenant(name_suffix: str) -> str:
    """Real integration (2026-08-22): search_service now delegates to
    ConversationService.process_turn() against the real, RLS-enforced DB —
    placeholder tenant_ids like "tenant_0" no longer round-trip the way they
    did against the old, disconnected, in-memory-only Module 4 client."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Fuzzy Stress Test {name_suffix}", "domain": f"fuzzystress-{name_suffix}.example.com"},
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
async def test_phonetic_scrambled_typos_multi_entity():
    """Scenario 1: Resolves severe phonetic misspelling & scrambled typos ('fenix', 'atls')."""
    query = "Prjct Fenix arcitectur and Atls deplyment status"
    normalized, hints = query_normalizer.normalize(query)

    assert "Project Phoenix" in hints
    assert "Project Atlas" in hints

@pytest.mark.asyncio
async def test_shorthand_payroll_abac_leakage_block():
    """Scenario 2: Resolves shorthand 'payrol' and ensures ABAC BLOCKS non-admin employee."""
    emp_identity = UserIdentity(user_id="emp_99", tenant_id="t1", roles=["Employee"], clearance_level="Internal")
    admin_identity = UserIdentity(user_id="adm_01", tenant_id="t1", roles=["Admin"], clearance_level="Restricted")
    
    query = "Ttn sfar salary payrol benchmark for VP level"
    normalized, hints = query_normalizer.normalize(query)

    assert "Project Titan" in hints
    assert "Executive Payroll & Compensation" in hints

    # Non-admin Employee MUST be blocked by PolicyEngine due to ABAC salary protection
    with pytest.raises(AuthorizationException):
        policy_engine.authorize_request(emp_identity, normalized)

    # Admin MUST be authorized cleanly
    policy_engine.authorize_request(admin_identity, normalized)

@pytest.mark.asyncio
async def test_extreme_multi_intent_compound_query():
    """Scenario 3: Handles complex multi-intent query with noisy characters and multiple entity typos."""
    complex_query = "  \n\t  What is the PHNIX Q3 milston status, Ttn budget, and Legl complince?  \r"
    normalized, hints = query_normalizer.normalize(complex_query)

    assert "Project Phoenix" in hints
    assert "Project Titan" in hints
    assert "Legal Department" in hints or "GDPR Compliance Verification" in hints

@pytest.mark.asyncio
async def test_concurrent_burst_20_multi_format_requests():
    """Scenario 4: Executes 20 simultaneous search requests with varied roles, formats, and tenants."""
    formats = ["markdown", "agent_schema", "dashboard", "mobile", "json"]
    roles_clearance = [
        (["Employee"], "Internal"),
        (["Manager"], "Confidential"),
        (["Admin"], "Restricted")
    ]

    real_tenants = [await _make_real_tenant(f"burst-{i}") for i in range(4)]
    try:
        async def single_search(idx):
            tenant_id = real_tenants[idx % 4]
            fmt = formats[idx % len(formats)]
            roles, clearance = roles_clearance[idx % len(roles_clearance)]
            identity = UserIdentity(user_id=f"user_{idx}", tenant_id=tenant_id, roles=roles, clearance_level=clearance)

            # Non-salary query to allow successful execution
            req = SearchRequest(query=f"Project Phoenix architectural status for task {idx}", format=fmt)
            res = await search_service.execute_search(req, identity, f"corr_burst_{idx}")
            return res

        results = await asyncio.gather(*[single_search(i) for i in range(20)])
        assert len(results) == 20
        for idx, res in enumerate(results):
            assert res is not None
    finally:
        for t in real_tenants:
            await _cleanup_real_tenant(t)
