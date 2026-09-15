"""
Policy Provider Interface
"""
from abc import ABC, abstractmethod
from app.retrieval.domain.retrieval import RetrievalPipelineContext

class IPolicyProvider(ABC):
    @abstractmethod
    async def validate_policy(self, ctx: RetrievalPipelineContext) -> bool:
        """Validates tenant authorization, confidentiality bounds, and resource budgets."""
        pass
