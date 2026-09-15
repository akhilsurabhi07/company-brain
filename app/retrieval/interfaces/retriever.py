"""
Retriever Interface
"""
from abc import ABC, abstractmethod
from typing import List
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext
from app.retrieval.domain.query import RetrievalPlan

class IRetriever(ABC):
    @abstractmethod
    async def retrieve(self, ctx: RetrievalPipelineContext, plan: RetrievalPlan) -> List[Candidate]:
        """Retrieves raw candidates from specified data sources."""
        pass
