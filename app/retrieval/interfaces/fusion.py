"""
Fusion Engine Interface
"""
from abc import ABC, abstractmethod
from typing import List
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext

class IFusionEngine(ABC):
    @abstractmethod
    async def fuse(self, ctx: RetrievalPipelineContext, candidate_pools: List[List[Candidate]], strategy_name: str = "rrf") -> List[Candidate]:
        """Fuses multi-modal candidate pools into a single ranked candidate list."""
        pass
