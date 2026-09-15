"""
Reciprocal Rank Fusion (RRF) Strategy
"""
from typing import List
from app.retrieval.domain.retrieval import Candidate

def apply_rrf(candidate_pools: List[List[Candidate]], k_constant: float = 60.0) -> List[Candidate]:
    """Applies Reciprocal Rank Fusion formula: S(d) = sum(1 / (k + R_m(d)))"""
    rrf_scores = {}
    candidate_map = {}

    for pool in candidate_pools:
        for rank, cand in enumerate(pool, start=1):
            cand_id = cand.id
            if cand_id not in candidate_map:
                candidate_map[cand_id] = cand
            rrf_scores[cand_id] = rrf_scores.get(cand_id, 0.0) + (1.0 / (k_constant + rank))

    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    fused_candidates = []
    for cid in sorted_ids:
        c = candidate_map[cid]
        c.score = rrf_scores[cid]
        fused_candidates.append(c)

    return fused_candidates
