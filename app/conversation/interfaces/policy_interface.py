"""Abstract Policy Engine Interface."""

from abc import ABC, abstractmethod
from typing import Dict, Any
from pydantic import BaseModel, Field


class PolicyEvaluationResult(BaseModel):
    is_allowed: bool
    policy_name: str
    reason: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BasePolicyEngine(ABC):
    """Abstract contract for policy enforcement."""

    @abstractmethod
    async def evaluate_request(
        self, tenant_id: str, user_id: str, prompt: str, context: Dict[str, Any]
    ) -> PolicyEvaluationResult:
        pass
