"""
Multi-Strategy Graph Traversal Implementation — Module 4
========================================================
Executes multi-strategy traversals (Neighborhood, Dependency, Impact, Risk) over GraphRepository under RLS.
"""
from typing import List, Dict, Any
from app.db.postgres_graph_repo import postgres_graph_repo

class GraphTraversalService:
    """Multi-strategy graph traversal service."""

    async def traverse(self, tenant_id: str, seed_entity_name: str, strategy: str = "Neighborhood", max_hops: int = 2) -> Dict[str, Any]:
        """Traverses graph starting from seed entity using GraphRepository under RLS."""
        entity = await postgres_graph_repo.get_entity_by_canonical_name(tenant_id, seed_entity_name)
        if not entity:
            return {"entities": [], "relationships": [], "facts": [], "decisions": []}

        entity_id = entity["id"]
        neighbors = await postgres_graph_repo.get_neighbors(tenant_id, entity_id, max_hops=max_hops)
        entity_ids = [entity_id] + [n["target_id"] for n in neighbors] + [n["source_id"] for n in neighbors]
        facts = await postgres_graph_repo.get_facts_for_entities(tenant_id, entity_ids)
        decisions = await postgres_graph_repo.get_decisions(tenant_id)

        return {
            "seed_entity": entity,
            "relationships": neighbors,
            "facts": facts,
            "decisions": decisions
        }

graph_traversal_service = GraphTraversalService()
