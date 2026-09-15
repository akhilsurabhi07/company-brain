"""
GraphRAG Reranker Implementation — Module 4
===========================================
Reuses BAAI/bge-reranker-large cross-encoder model to score and rerank candidates.
"""
from typing import List
from app.retrieval.interfaces.reranker import IReranker
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext
from app.embeddings.bge_reranker import bge_reranker

class GraphRAGReranker(IReranker):
    """Reranks candidate items using BAAI/bge-reranker-large cross-encoder."""

    async def rerank(self, ctx: RetrievalPipelineContext, candidates: List[Candidate], top_k: int = 10) -> List[Candidate]:
        if not candidates:
            return []

        passages = [c.content for c in candidates]
        try:
            scores = bge_reranker.rerank(ctx.query, passages)
            for idx, c in enumerate(candidates):
                c.score = float(scores[idx]) if idx < len(scores) else c.score
        except Exception:
            pass  # Fallback to existing candidate score ranking if reranker model is unavailable

        sorted_candidates = sorted(candidates, key=lambda x: x.score, reverse=True)
        return sorted_candidates[:top_k]

graphrag_reranker = GraphRAGReranker()
