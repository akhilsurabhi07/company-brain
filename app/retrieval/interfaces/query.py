"""
Query Intelligence Interface
"""
from abc import ABC, abstractmethod
from app.retrieval.domain.query import QueryAnalysis
from app.retrieval.domain.retrieval import RetrievalPipelineContext

class IQueryIntelligence(ABC):
    @abstractmethod
    async def analyze(self, ctx: RetrievalPipelineContext) -> QueryAnalysis:
        """Analyzes query intent, entities, temporal scope, and constraints."""
        pass
