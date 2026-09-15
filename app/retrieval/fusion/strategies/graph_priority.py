"""
Graph Priority Fusion Strategy
"""
from typing import List
from app.retrieval.domain.retrieval import Candidate
from app.retrieval.fusion.strategies.weighted_rrf import apply_weighted_rrf

def apply_graph_priority_fusion(candidate_pools: List[List[Candidate]]) -> List[Candidate]:
    """Gives higher weight multiplier (2.5x) to graph candidates."""
    # Assuming candidate_pools = [dense_pool, bm25_pool, graph_pool]
    weights = [1.0, 1.0, 2.5]
    return apply_weighted_rrf(candidate_pools, weights)
