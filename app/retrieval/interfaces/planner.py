"""
Execution Planner Interface
"""
from abc import ABC, abstractmethod
from app.retrieval.domain.query import QueryAnalysis, RetrievalPlan
from app.retrieval.domain.retrieval import RetrievalPipelineContext

class IExecutionPlanner(ABC):
    @abstractmethod
    async def plan(self, ctx: RetrievalPipelineContext, analysis: QueryAnalysis) -> RetrievalPlan:
        """Generates execution graph specifying retrieval strategies and budgets."""
        pass
