"""
Self-Hosted BGE Large Reranker Engine — Module 4
================================================
Uses BAAI/bge-reranker-large or cosine similarity fallback for cross-encoder reranking.
"""
from typing import List
from app.embeddings.bge_embedder import bge_embedder

class BGEReranker:
    """Self-Hosted BAAI/bge-reranker-large Cross-Encoder Engine."""

    MODEL_ID = "BAAI/bge-reranker-large"

    def rerank(self, query: str, passages: List[str]) -> List[float]:
        """Scores relevance between query and passages via cosine similarity
        on real embeddings. Real-question testing 2026-08-21 found this used
        to swallow ANY failure and return an identical fabricated 0.85
        "relevance" score for every passage — meaning a genuinely irrelevant
        candidate would look exactly as relevant as a perfect match whenever
        the embedder had a problem, and the caller's own honest
        keep-existing-ranking fallback (graphrag_reranker.py) never got a
        chance to run because this never actually raised. Letting the real
        exception propagate now lets that existing honest fallback do its
        job instead."""
        if not passages:
            return []

        q_emb = bge_embedder.embed_texts([query])[0]
        p_embs = bge_embedder.embed_texts(passages)
        scores = []
        for p_emb in p_embs:
            score = sum(a * b for a, b in zip(q_emb, p_emb))
            scores.append(round(float(score), 4))
        return scores

bge_reranker = BGEReranker()
