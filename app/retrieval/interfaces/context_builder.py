"""
Context Builder Interface
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext
from app.retrieval.domain.context import KnowledgeContext

class IContextBuilder(ABC):
    @abstractmethod
    async def build(
        self,
        ctx: RetrievalPipelineContext,
        candidates: List[Candidate],
        graph_data: Dict[str, Any],
        synthesized_data: Dict[str, Any]
    ) -> KnowledgeContext:
        """Assembles the final KnowledgeContext v1 object."""
        pass
