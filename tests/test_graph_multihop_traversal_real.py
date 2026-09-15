"""
Real test for Module 4 gaps found via inspection 2026-08-22: neither the live repo
(app/db/postgres_knowledge_repo.py) nor the parallel, never-wired-in Module 4 pipeline
(app/db/postgres_graph_repo.py — same underlying tables, duplicate access code) ever
actually implemented multi-hop graph traversal. Both accepted a hop-depth parameter
and silently ignored it, always returning only direct (1-hop) relationships.

Fixed get_relationships_for_entity_name (the live one) to genuinely walk the graph
via a bounded recursive CTE when max_hops > 1. Default remains 1 (unchanged prior
behavior for every existing caller); this only activates for a caller that
explicitly asks for more hops.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.db.postgres_knowledge_repo import postgres_knowledge_repo

TEST_TENANT = "88888888-8888-8888-8888-888888888820"


@pytest.mark.asyncio
async def test_multihop_traversal_reaches_a_real_second_hop_entity():
    """Real chain: Person --leads--> Project --depends_on--> Vendor. A 1-hop query from
    Person must NOT see Vendor; a 2-hop query must."""
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Multihop Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"multihoptest-{TEST_TENANT[:8]}.example.com"},
        )

        entities = {"Test Person": "person", "Test Project": "project", "Test Vendor": "vendor"}
        ids = {}
        for name, etype in entities.items():
            eid = str(uuid.uuid4())
            ids[name] = eid
            await session.execute(text("""
                INSERT INTO graph_entities (id, tenant_id, entity_type, canonical_name, state, confidence_score, trust_score, attributes, governance_tags, is_current)
                VALUES (:id, :t, :etype, :name, 'active', 0.95, 0.95, '{}', '{}', true)
            """), {"id": eid, "t": TEST_TENANT, "etype": etype, "name": name})

        rel_ids = []
        for src, tgt, rel in [("Test Person", "Test Project", "leads"), ("Test Project", "Test Vendor", "depends_on")]:
            rid = str(uuid.uuid4())
            rel_ids.append(rid)
            await session.execute(text("""
                INSERT INTO graph_relationships (id, tenant_id, source_entity_id, target_entity_id, relation_type, state, confidence_score, attributes, is_current)
                VALUES (:id, :t, :src, :tgt, :rel, 'active', 0.9, '{}', true)
            """), {"id": rid, "t": TEST_TENANT, "src": ids[src], "tgt": ids[tgt], "rel": rel})
        await session.commit()

    try:
        edges_1hop = await postgres_knowledge_repo.get_relationships_for_entity_name(TEST_TENANT, "Test Person")
        targets_1hop = {e["target"] for e in edges_1hop} | {e["source"] for e in edges_1hop}
        assert "Test Vendor" not in targets_1hop, "1-hop (default, unchanged behavior) must NOT reach the second-hop entity"
        assert "Test Project" in targets_1hop

        edges_2hop = await postgres_knowledge_repo.get_relationships_for_entity_name(TEST_TENANT, "Test Person", max_hops=2)
        all_names_2hop = {e["target"] for e in edges_2hop} | {e["source"] for e in edges_2hop}
        assert "Test Vendor" in all_names_2hop, "2-hop traversal must genuinely reach the second-hop entity"
        hops = {e["relation"]: e["hop"] for e in edges_2hop}
        assert hops.get("depends_on") == 2, "the second-hop edge must be correctly reported as hop 2, not silently hop 1"
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            for rid in rel_ids:
                await session.execute(text("DELETE FROM graph_relationships WHERE id = :id"), {"id": rid})
            for eid in ids.values():
                await session.execute(text("DELETE FROM graph_entities WHERE id = :id"), {"id": eid})
            await session.commit()


@pytest.mark.asyncio
async def test_multihop_traversal_is_tenant_isolated():
    """A different tenant's identically-named graph must never be reachable."""
    other_tenant = "88888888-8888-8888-8888-888888888821"
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": other_tenant})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Multihop Isolation Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": other_tenant, "domain": f"multihopiso-{other_tenant[:8]}.example.com"},
        )
        await session.commit()

    try:
        edges = await postgres_knowledge_repo.get_relationships_for_entity_name(other_tenant, "Test Person", max_hops=2)
        assert edges == [], "a tenant with no real graph data must get an empty result, never another tenant's real graph"
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": other_tenant})
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": other_tenant})
            await session.commit()
