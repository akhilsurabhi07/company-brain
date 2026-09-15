"""
Dense Priority Fusion Strategy
"""
from typing import List
from app.retrieval.domain.retrieval import Candidate
from app.retrieval.fusion.strategies.weighted_rrf import apply_weighted_rrf

def apply_dense_priority_fusion(candidate_pools: List[List[Candidate]]) -> List[Candidate]:
    """Gives higher weight multiplier (2.5x) to dense vector candidates."""
    weights = [2.5, 1.0, 1.0]
    return apply_weighted_rrf(candidate_pools, weights)
