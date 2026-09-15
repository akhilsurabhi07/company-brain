"""Subsystem 7: Runtime Orchestrator."""

import asyncio
import time
from typing import Dict, Any, AsyncGenerator, List
from app.conversation.interfaces.llm_provider import GenerationRequest, GenerationResponse
from app.conversation.domain.response_payload import MultimodalResponsePayload
from app.conversation.providers.factory import ProviderFactory
from app.conversation.interfaces.exceptions import LLMProviderOfflineException
from app.conversation.runtime.provider_health import provider_health_monitor

# Map model_name values used by the service → factory provider keys
_MODEL_TO_PROVIDER = {
    "GEMINI": "GEMINI",
    "OPENAI": "OPENAI",
    "ANTHROPIC": "ANTHROPIC",
    "AZURE": "AZURE",
    "OLLAMA": "OLLAMA",
    "VLLM": "VLLM",
    "GROQ": "GROQ",
    "HUGGINGFACE": "HUGGINGFACE",
    "LOCAL": "LOCAL",
    "MOCK": "MOCK",
    "mock": "MOCK",
    # Intelligent router may return these strings
    "gpt-4o": "OPENAI",
    "claude-3-5-sonnet": "ANTHROPIC",
    "gemini-1.5-pro": "GEMINI",
    "gemini-2.0-flash": "GEMINI",
    "gemini-3.6-flash": "GEMINI",
    "llama3-70b-8192": "GROQ",  # legacy alias, model itself is decommissioned on Groq's side
    "openai/gpt-oss-120b": "GROQ",
    "multi-llm-consensus": "OPENAI",
}


class RuntimeOrchestrator:
    """Orchestrates LLM generation with real cascading failover across every configured
    provider, and timeout management. Each provider adapter is responsible for its own
    internal retry policy (e.g. Gemini/Groq/HuggingFace back off on 429 internally) and
    must RAISE on genuine failure — never silently substitute canned/templated text. This
    orchestrator's job is purely: try the requested provider, and if it genuinely fails,
    move to the next real provider, in order, until one succeeds."""

    # Default cascade order for real, hosted providers (self-hosted OLLAMA/VLLM and the
    # explicit MOCK testing provider are never auto-cascaded into). LOCAL (a real,
    # self-hosted open-source model — see factory.py) is deliberately LAST: paid/
    # hosted providers are tried first when actually available, and LOCAL only
    # engages once every one of them has genuinely failed — added 2026-08-21 so a
    # simultaneous outage across all paid providers gets a real answer instead of
    # a canned "I can't answer" degraded response.
    _CASCADE_ORDER = ["OPENAI", "GROQ", "GEMINI", "ANTHROPIC", "HUGGINGFACE", "LOCAL"]

    def __init__(self, max_retries: int = 3, timeout_seconds: float = 60.0):
        self.max_retries = max_retries  # kept for API compatibility; no longer used to
                                          # retry a single provider (each adapter owns that)
        self.timeout_seconds = timeout_seconds

    def _build_cascade(self, provider_key: str) -> List[str]:
        """Requested provider first, then the rest of the real-provider cascade, deduped."""
        ordered = [provider_key] + [p for p in self._CASCADE_ORDER if p != provider_key]
        return ordered

    async def execute_generation(self, request: GenerationRequest) -> GenerationResponse:
        provider_key = _MODEL_TO_PROVIDER.get(request.model_name, "OPENAI")

        # MOCK is an explicit, intentional choice (offline demo/testing) — never cascade
        # through real providers for it, and never cascade INTO it from a real provider.
        if provider_key in ("MOCK", "mock", "OLLAMA", "VLLM", "AZURE"):
            print(f"[RuntimeOrchestrator] Using provider: {provider_key} (model_name={request.model_name})")
            return await ProviderFactory.get_provider(provider_key).generate(request)

        cascade = self._build_cascade(provider_key)
        last_error: Exception = RuntimeError("No provider attempted.")

        for candidate_key in cascade:
            # Real bug fixed live 2026-09-15: provider_health_monitor's circuit
            # breaker was fully implemented and even being fed real
            # success/error events, but nothing ever consulted is_available()
            # before attempting a provider -- a provider confirmed dead (observed
            # live: OpenAI returning 429 insufficient_quota on every call) kept
            # getting retried on every single real query, wasting a real API
            # attempt and real latency every time before falling through to the
            # next provider. Skip a circuit-broken provider outright; if every
            # candidate is broken, the loop falls through to the honest
            # degraded response below, same as any other all-providers-failed case.
            health_key = candidate_key.lower()
            if not provider_health_monitor.is_available(health_key):
                print(f"[RuntimeOrchestrator] Skipping {candidate_key}: circuit open (recently failing).")
                last_error = RuntimeError(f"{candidate_key} circuit open")
                continue

            provider = ProviderFactory.get_provider(candidate_key)
            print(f"[RuntimeOrchestrator] Trying provider: {candidate_key} (model_name={request.model_name})")
            attempt_start = time.time()
            try:
                response = await asyncio.wait_for(provider.generate(request), timeout=self.timeout_seconds)
                provider_health_monitor.record_success(health_key, (time.time() - attempt_start) * 1000.0)
                if candidate_key != provider_key:
                    print(f"[RuntimeOrchestrator] Failed over from {provider_key} to {candidate_key} successfully.")
                return response
            except LLMProviderOfflineException as e:
                print(f"[RuntimeOrchestrator] Provider {candidate_key} offline/unconfigured: {e}")
                provider_health_monitor.record_error(health_key, str(e))
                last_error = e
            except asyncio.TimeoutError as e:
                print(f"[RuntimeOrchestrator] Provider {candidate_key} timed out after {self.timeout_seconds}s.")
                provider_health_monitor.record_error(health_key, str(e))
                last_error = e
            except Exception as e:
                print(f"[RuntimeOrchestrator] Provider {candidate_key} failed: {e}")
                provider_health_monitor.record_error(health_key, str(e))
                last_error = e

        # Every real provider in the cascade failed — say so honestly. Do NOT fabricate a
        # "grounded" answer here; that would be indistinguishable from a real one to the
        # user and is exactly the failure mode this cascade exists to eliminate.
        print(f"[RuntimeOrchestrator] All providers in cascade {cascade} failed. Last error: {last_error}")
        payload = MultimodalResponsePayload(
            text_content=(
                "I wasn't able to reach any AI model provider just now (all configured "
                "providers failed or are unavailable), so I can't answer this safely. "
                "Please try again in a moment."
            ),
            citations=[],
        )
        return GenerationResponse(
            payload=payload,
            model_name="none",
            provider_name="degraded",
            latency_ms=0.0,
            cost_usd=0.0,
        )

    async def execute_streaming(self, request: GenerationRequest) -> AsyncGenerator[Dict[str, Any], None]:
        provider_key = _MODEL_TO_PROVIDER.get(request.model_name, "OPENAI")
        provider = ProviderFactory.get_provider(provider_key)
        async for chunk in provider.generate_stream(request):
            yield chunk
