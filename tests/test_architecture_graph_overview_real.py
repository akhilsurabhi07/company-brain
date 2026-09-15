"""
Module 6B — real "Architecture Graph" standalone browse view (2026-08-23).

Before this, the sidebar's "Architecture Graph" was an honest "Soon"
placeholder. The real knowledge graph rendering already existed
(/api/v1/knowledge/graph-context, used by the chat "Graph" button) but
required a query matching a specific entity — there was no way to just
browse the tenant's whole graph. This adds that query-free overview,
reusing the same real graph_entities/graph_relationships tables and the
same node/edge response shape.
"""
import uuid
import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory
from tests.conftest import auth_headers_for

GRAPH_URL = "/api/v1/knowledge/architecture-graph"


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Arch Graph Test {name_suffix}", "domain": f"archgraph-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM graph_relationships WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM graph_entities WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_empty_tenant_gets_honest_no_entities_message():
    tenant_id = await _make_tenant("empty")
    try:
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.get(GRAPH_URL, params={"tenant_id": tenant_id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["matched"] is False
        assert body["nodes"] == []
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_returns_real_entities_ranked_by_connection_count():
    tenant_id = await _make_tenant("ranked")
    try:
        entity_ids = {}
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            for name, etype in [("Elena Rostova", "person"), ("Project Falcon", "project"), ("Stripe", "vendor")]:
                eid = str(uuid.uuid4())
                entity_ids[name] = eid
                await session.execute(text("""
                    INSERT INTO graph_entities (id, tenant_id, entity_type, canonical_name, state, confidence_score, trust_score, attributes, governance_tags, is_current)
                    VALUES (:id, :t, :etype, :name, 'active', 0.95, 0.95, '{}', '{}', true)
                """), {"id": eid, "t": tenant_id, "etype": etype, "name": name})
            for src, tgt, rel in [("Elena Rostova", "Project Falcon", "leads"), ("Project Falcon", "Stripe", "depends_on")]:
                await session.execute(text("""
                    INSERT INTO graph_relationships (id, tenant_id, source_entity_id, target_entity_id, relation_type, state, confidence_score, attributes, is_current)
                    VALUES (:id, :t, :src, :tgt, :rel, 'active', 0.9, '{}', true)
                """), {"id": str(uuid.uuid4()), "t": tenant_id, "src": entity_ids[src], "tgt": entity_ids[tgt], "rel": rel})
            await session.commit()

        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.get(GRAPH_URL, params={"tenant_id": tenant_id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["matched"] is True
        node_labels = {n["label"] for n in body["nodes"]}
        assert node_labels == {"Elena Rostova", "Project Falcon", "Stripe"}
        # "Project Falcon" has 2 real relationships (leads + depends_on), the
        # other two have 1 each — it must rank first.
        assert body["nodes"][0]["label"] == "Project Falcon"
        edge_labels = {(e["label"]) for e in body["edges"]}
        assert edge_labels == {"leads", "depends_on"}
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_architecture_graph_is_tenant_isolated():
    tenant_a = await _make_tenant("iso-a")
    tenant_b = await _make_tenant("iso-b")
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_a})
            await session.execute(text("""
                INSERT INTO graph_entities (id, tenant_id, entity_type, canonical_name, state, confidence_score, trust_score, attributes, governance_tags, is_current)
                VALUES (:id, :t, 'project', 'Tenant A Only Project', 'active', 0.95, 0.95, '{}', '{}', true)
            """), {"id": str(uuid.uuid4()), "t": tenant_a})
            await session.commit()

        headers_b = auth_headers_for(tenant_b, role="admin")
        async with await _client() as client:
            resp = await client.get(GRAPH_URL, params={"tenant_id": tenant_b}, headers=headers_b)
        assert resp.status_code == 200
        assert resp.json()["nodes"] == []
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
