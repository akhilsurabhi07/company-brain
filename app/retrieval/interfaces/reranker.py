"""
Reranker Interface
"""
from abc import ABC, abstractmethod
from typing import List
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext

class IReranker(ABC):
    @abstractmethod
    async def rerank(self, ctx: RetrievalPipelineContext, candidates: List[Candidate], top_k: int = 10) -> List[Candidate]:
        """Scoring candidates using cross-encoder models."""
        pass
