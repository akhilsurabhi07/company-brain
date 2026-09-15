"""
Real bug found 2026-08-23, once organizational_health_engine's score was
surfaced in a real UI panel for the first time (Module 6B "Dashboards"):
total_entities was accepted as a parameter but never used in the score
formula — a brand-new tenant with zero real content scored a perfect 100
"Knowledge Quality Score" (zero conflicts/orphans/gaps, simply because
there's nothing there yet), directly contradicting the real, correctly-
computed 0% Knowledge Freshness / Documentation Coverage shown right next to
it in the same panel. Fixed: zero entities now honestly scores 0.
"""
import uuid
import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory
from app.graph.intelligence.organizational_health_engine import organizational_health_engine
from tests.conftest import auth_headers_for


def test_zero_entities_scores_zero_not_a_false_perfect_100():
    health = organizational_health_engine.compute_tenant_health(
        tenant_id="t1", total_entities=0, orphan_projects=0,
        unassigned_tasks=0, active_conflicts=0, knowledge_gaps=0,
    )
    assert health.quality_score == 0.0


def test_real_content_with_no_issues_still_scores_high():
    health = organizational_health_engine.compute_tenant_health(
        tenant_id="t1", total_entities=50, orphan_projects=0,
        unassigned_tasks=0, active_conflicts=0, knowledge_gaps=0,
    )
    assert health.quality_score == 100.0


@pytest.mark.asyncio
async def test_dashboards_endpoint_is_honest_for_a_fresh_empty_tenant():
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": "Health Score Test", "domain": f"healthscore-{tenant_id[:8]}.example.com"},
        )
        await session.commit()
    try:
        headers = auth_headers_for(tenant_id, role="admin")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/knowledge/health", params={"tenant_id": tenant_id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["quality_score"] == 0.0, f"a fresh, empty tenant must not show a false perfect score, got: {body}"
    finally:
        async with async_session_factory() as session:
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
            await session.commit()
