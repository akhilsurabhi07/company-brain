"""
Evidence Orchestrator Implementation — Module 4
===============================================
Deduplicates candidate items, collapses repeated text chunks, and constructs coherent evidence groups.
"""
from typing import List, Dict, Any
from app.retrieval.domain.retrieval import Candidate
from app.retrieval.domain.evidence import Evidence, EvidenceGroup

class EvidenceOrchestrator:
    """Orchestrates candidate items into structured evidence groups."""

    def orchestrate(self, candidates: List[Candidate]) -> List[EvidenceGroup]:
        seen_ids = set()
        deduped: List[Candidate] = []

        for c in candidates:
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                deduped.append(c)

        chunk_group = EvidenceGroup(group_id="chunks", group_name="Document Chunks", items=[])
        fact_group = EvidenceGroup(group_id="facts", group_name="Knowledge Facts", items=[])
        rel_group = EvidenceGroup(group_id="relationships", group_name="Graph Relationships", items=[])

        for c in deduped:
            ev = Evidence(
                id=c.id,
                content=c.content,
                evidence_type=c.item_type,
                relevance_score=c.score
            )
            if "chunk" in c.item_type:
                chunk_group.items.append(ev)
            elif "fact" in c.item_type:
                fact_group.items.append(ev)
            else:
                rel_group.items.append(ev)

        groups = [g for g in [chunk_group, fact_group, rel_group] if g.items]
        return groups

evidence_orchestrator = EvidenceOrchestrator()
