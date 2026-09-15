"""Test Suite 2: Module 6A Runtime Orchestration Tests.

These tests exercise RuntimeOrchestrator's cascading-failover LOGIC in isolation via
mocked providers, rather than depending on real provider accounts having quota
available (OpenAI/Gemini free-tier quota is not something CI/local runs control, and
asserting on live results made this suite flaky by design). Real end-to-end provider
behavior is covered separately by the live smoke-tested benchmark suite.
"""

import pytest
from app.conversation.interfaces.llm_provider import (
    GenerationRequest,
    GenerationResponse,
    BaseLLMProvider,
)
from app.conversation.interfaces.exceptions import LLMProviderOfflineException
from app.conversation.domain.response_payload import MultimodalResponsePayload
from app.conversation.runtime.orchestrator import RuntimeOrchestrator
from app.conversation.providers.factory import ProviderFactory


class _FakeProvider(BaseLLMProvider):
    """A provider stub that either raises or returns a canned success, so cascade
    logic can be tested deterministically."""

    def __init__(self, name: str, fail_with: Exception = None):
        self._name = name
        self._fail_with = fail_with

    @property
    def provider_name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        if self._fail_with is not None:
            raise self._fail_with
        return GenerationResponse(
            payload=MultimodalResponsePayload(text_content=f"Answer from {self._name}", citations=[]),
            model_name=self._name.lower(),
            provider_name=self._name,
            latency_ms=1.0,
        )

    async def generate_stream(self, request: GenerationRequest):
        yield {"type": "token", "content": "stub"}
        yield {"type": "status", "status": "COMPLETED"}


@pytest.mark.asyncio
async def test_runtime_orchestration_fails_over_to_next_real_provider(monkeypatch):
    """OPENAI fails (e.g. quota exhausted) -> cascade must genuinely try GROQ next and
    return ITS real answer/provider_name, not a fabricated OpenAI-branded response."""
    fakes = {
        "OPENAI": _FakeProvider("OpenAI", fail_with=LLMProviderOfflineException("quota exhausted")),
        "GROQ": _FakeProvider("Groq"),
        "GEMINI": _FakeProvider("Gemini"),
        "ANTHROPIC": _FakeProvider("Anthropic"),
        "HUGGINGFACE": _FakeProvider("HuggingFace"),
    }
    monkeypatch.setattr(ProviderFactory, "get_provider", classmethod(lambda cls, key, **kw: fakes[key]))

    orchestrator = RuntimeOrchestrator()
    req = GenerationRequest(prompt="Test prompt", persona="ENGINEER", mode="ASK", model_name="OPENAI")
    res = await orchestrator.execute_generation(req)

    assert res.provider_name == "Groq"
    assert res.payload.text_content == "Answer from Groq"
    assert res.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_runtime_orchestration_reports_honest_failure_when_all_providers_fail(monkeypatch):
    """When every real provider in the cascade fails, the orchestrator MUST say so
    honestly (provider_name == 'degraded') rather than fabricate a 'successful' answer."""
    fakes = {
        # LOCAL (the real, self-hosted open-source fallback added 2026-08-21) must be
        # included here too — it's a real 6th entry in the cascade now, and this test
        # is specifically about the true worst case where nothing at all works.
        key: _FakeProvider(key, fail_with=LLMProviderOfflineException("unconfigured"))
        for key in ["OPENAI", "GROQ", "GEMINI", "ANTHROPIC", "HUGGINGFACE", "LOCAL"]
    }
    monkeypatch.setattr(ProviderFactory, "get_provider", classmethod(lambda cls, key, **kw: fakes[key]))

    orchestrator = RuntimeOrchestrator()
    req = GenerationRequest(prompt="Test prompt", persona="ENGINEER", mode="ASK", model_name="OPENAI")
    res = await orchestrator.execute_generation(req)

    assert res.provider_name == "degraded"
    assert "wasn't able to reach" in res.payload.text_content.lower()


def test_provider_factory():
    p_gpt = ProviderFactory.get_provider("OPENAI")
    p_claude = ProviderFactory.get_provider("ANTHROPIC")

    assert p_gpt.provider_name == "OpenAI"
    assert p_claude.provider_name == "Anthropic"
