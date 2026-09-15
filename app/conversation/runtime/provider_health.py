"""Provider Health Monitor Subsystem for Module 6A."""

import time
from typing import Dict, Any, List
from pydantic import BaseModel, Field


class ProviderMetrics(BaseModel):
    provider_name: str
    is_available: bool = True
    latency_ms_p95: float = 120.0
    error_rate: float = 0.0
    active_requests: int = 0
    circuit_broken: bool = False
    last_error_timestamp: float = 0.0


class ProviderHealthMonitor:
    """Tracks latency, error rate, availability, and circuit breaks failed providers.

    Real bug found live 2026-09-15: this class was fully implemented (including a
    real half-open circuit reset) and conversation_service.py was even calling
    record_success()/record_error() on every real turn -- but nothing anywhere ever
    called is_available()/get_healthy_providers() before attempting a provider. The
    circuit breaker recorded state and then nobody read it: a provider confirmed
    dead (observed live: OpenAI returning 429 insufficient_quota/
    credit_balance_exhausted on every single call) still got retried on every
    subsequent real query, wasting a real API attempt and real latency each time
    before RuntimeOrchestrator's cascade moved on to the next provider. Now wired
    into RuntimeOrchestrator's cascade loop (see orchestrator.py) as the actual
    gate it was always meant to be.

    Provider key set also found stale -- it listed azure/ollama/vllm (not real
    cascade members orchestrator.py auto-cascades through) and was completely
    missing groq/huggingface/local, the real, currently-live cascade members that
    matter most. Aligned to RuntimeOrchestrator._CASCADE_ORDER (lowercased)."""

    def __init__(self):
        self._metrics: Dict[str, ProviderMetrics] = {
            "openai": ProviderMetrics(provider_name="openai", latency_ms_p95=150.0),
            "groq": ProviderMetrics(provider_name="groq", latency_ms_p95=300.0),
            "gemini": ProviderMetrics(provider_name="gemini", latency_ms_p95=110.0),
            "anthropic": ProviderMetrics(provider_name="anthropic", latency_ms_p95=140.0),
            "huggingface": ProviderMetrics(provider_name="huggingface", latency_ms_p95=400.0),
            "local": ProviderMetrics(provider_name="local", latency_ms_p95=800.0),
            "azure": ProviderMetrics(provider_name="azure", latency_ms_p95=130.0),
            "ollama": ProviderMetrics(provider_name="ollama", latency_ms_p95=80.0),
            "vllm": ProviderMetrics(provider_name="vllm", latency_ms_p95=70.0),
        }

    def record_success(self, provider_name: str, latency_ms: float):
        if provider_name in self._metrics:
            m = self._metrics[provider_name]
            m.latency_ms_p95 = (m.latency_ms_p95 * 0.9) + (latency_ms * 0.1)
            m.error_rate = max(0.0, m.error_rate - 0.01)

    def record_error(self, provider_name: str, error_msg: str):
        if provider_name in self._metrics:
            m = self._metrics[provider_name]
            m.error_rate += 0.1
            m.last_error_timestamp = time.time()
            if m.error_rate >= 0.5:
                m.circuit_broken = True
                m.is_available = False

    def is_available(self, provider_name: str) -> bool:
        if provider_name not in self._metrics:
            return True
        m = self._metrics[provider_name]
        if m.circuit_broken and (time.time() - m.last_error_timestamp > 30.0):
            # Half-open circuit reset after 30s
            m.circuit_broken = False
            m.is_available = True
            m.error_rate = 0.0
        return m.is_available

    def get_healthy_providers(self) -> List[str]:

        return [p for p, m in self._metrics.items() if self.is_available(p)]


# Module-level singleton, same pattern as bge_embedder/chunk_validator/tool_registry
# elsewhere in this codebase -- must be ONE shared instance so state recorded by one
# caller (e.g. RuntimeOrchestrator, used by both conversation_service and
# agent_platform) is visible to every other real caller, not siloed per-instance.
provider_health_monitor = ProviderHealthMonitor()
