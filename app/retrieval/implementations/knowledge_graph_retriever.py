"""
Knowledge Graph Retriever Implementation — Module 4
===================================================
Calls GraphTraversalService to retrieve candidates from PostgreSQL graph under RLS.
"""
from typing import List
from app.retrieval.interfaces.retriever import IRetriever
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext
from app.retrieval.domain.query import RetrievalPlan
from app.retrieval.implementations.graph_traversal import graph_traversal_service

class KnowledgeGraphRetriever(IRetriever):
    """Retrieves graph candidates via multi-strategy graph traversal."""

    async def retrieve(self, ctx: RetrievalPipelineContext, plan: RetrievalPlan) -> List[Candidate]:
        candidates = []
        analysis = ctx.analysis or {}
        entities = analysis.get("entities", [])

        for ent_name in entities:
            res = await graph_traversal_service.traverse(ctx.tenant_id, ent_name, max_hops=plan.hop_depth)
            seed = res.get("seed_entity")
            if seed:
                candidates.append(Candidate(
                    id=seed["id"],
                    item_type="graph_entity",
                    content=f"Entity: {seed['canonical_name']} ({seed['entity_type']})",
                    score=0.95,
                    source_metadata={"canonical_name": seed["canonical_name"], "entity_type": seed["entity_type"]}
                ))
            for rel in res.get("relationships", []):
                candidates.append(Candidate(
                    id=rel["relationship_id"],
                    item_type="graph_relationship",
                    content=f"{rel['source_name']} --[{rel['relationship_type']}]--> {rel['target_name']}",
                    score=rel.get("weight", 0.90),
                    source_metadata=rel
                ))
            for fact in res.get("facts", []):
                candidates.append(Candidate(
                    id=fact["id"],
                    item_type="graph_fact",
                    content=f"Fact: {fact['fact_type']} {fact['metric_name']} = {fact['value']}",
                    score=0.90,
                    source_metadata=fact
                ))

        return candidates
