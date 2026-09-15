"""Subsystem 9: Provider Capability Registry."""

from typing import Dict, Optional
from pydantic import BaseModel, Field


class ModelCapabilities(BaseModel):
    model_id: str
    provider: str
    context_window_tokens: int
    supports_json: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_function_calling: bool = True
    cost_per_1k_tokens_usd: float = 0.002
    avg_latency_ms: float = 250.0
    availability_status: str = "ONLINE"


class CapabilityRegistry:
    """Registry storing model capabilities and specifications."""

    _MODELS: Dict[str, ModelCapabilities] = {
        "gpt-4o": ModelCapabilities(
            model_id="gpt-4o", provider="OpenAI", context_window_tokens=128000,
            supports_vision=True, cost_per_1k_tokens_usd=0.005, avg_latency_ms=180.0
        ),
        "claude-3-5-sonnet": ModelCapabilities(
            model_id="claude-3-5-sonnet", provider="Anthropic", context_window_tokens=200000,
            supports_vision=True, cost_per_1k_tokens_usd=0.003, avg_latency_ms=150.0
        ),
        "gemini-1.5-pro": ModelCapabilities(
            model_id="gemini-1.5-pro", provider="Gemini", context_window_tokens=1000000,
            supports_vision=True, cost_per_1k_tokens_usd=0.002, avg_latency_ms=210.0
        ),
    }

    @classmethod
    def get_capabilities(cls, model_id: str) -> Optional[ModelCapabilities]:
        return cls._MODELS.get(model_id, cls._MODELS["gpt-4o"])
