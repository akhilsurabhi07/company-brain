"""
Weighted Reciprocal Rank Fusion Strategy
"""
from typing import List, Dict
from app.retrieval.domain.retrieval import Candidate

def apply_weighted_rrf(candidate_pools: List[List[Candidate]], weights: List[float], k_constant: float = 60.0) -> List[Candidate]:
    """Applies Weighted RRF formula."""
    rrf_scores = {}
    candidate_map = {}

    for idx, pool in enumerate(candidate_pools):
        w = weights[idx] if idx < len(weights) else 1.0
        for rank, cand in enumerate(pool, start=1):
            cand_id = cand.id
            if cand_id not in candidate_map:
                candidate_map[cand_id] = cand
            rrf_scores[cand_id] = rrf_scores.get(cand_id, 0.0) + (w / (k_constant + rank))

    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    fused = []
    for cid in sorted_ids:
        c = candidate_map[cid]
        c.score = rrf_scores[cid]
        fused.append(c)

    return fused
