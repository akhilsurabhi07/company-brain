"""Abstract LLM Provider & Generation Request/Response Interfaces."""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.conversation.domain.response_payload import MultimodalResponsePayload


class GenerationRequest(BaseModel):
    prompt: str
    raw_query: str = ""
    history: Optional[Any] = None
    system_prompt: str = ""
    model_name: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 2048
    tenant_id: str = "default"
    user_id: str = "default"
    persona: str = "ENGINEER"
    mode: str = "ASK"


class GenerationResponse(BaseModel):
    payload: MultimodalResponsePayload
    model_name: str
    provider_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0


class BaseLLMProvider(ABC):
    """Abstract contract for LLM provider adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        pass

    @abstractmethod
    async def generate_stream(self, request: GenerationRequest) -> AsyncGenerator[Dict[str, Any], None]:
        pass
