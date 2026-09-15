"""Test Suite 6: Module 6A Multi-LLM Consensus Tests.

Providers are mocked so consensus LOGIC (agreement scoring, honest exclusion of
failed/unconfigured providers, honest failure when nothing responds) is tested
deterministically, independent of which real accounts currently have quota.
"""

import pytest
from app.conversation.interfaces.llm_provider import GenerationRequest, GenerationResponse
from app.conversation.interfaces.exceptions import LLMProviderOfflineException
from app.conversation.domain.response_payload import MultimodalResponsePayload
from app.conversation.orchestration.consensus import MultiLLMConsensusEngine
from app.conversation.providers.factory import ProviderFactory


class _FakeProvider:
    def __init__(self, name: str, text: str = None, fail: bool = False):
        self._name = name
        self._text = text
        self._fail = fail

    @property
    def provider_name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        if self._fail:
            raise LLMProviderOfflineException(f"{self._name} unavailable")
        return GenerationResponse(
            payload=MultimodalResponsePayload(text_content=self._text, citations=[]),
            model_name=self._name.lower(),
            provider_name=self._name,
            latency_ms=1.0,
        )


_AGREEING_TEXT = (
    "Under export control law, the company must screen all international shipments "
    "against the denied-parties list before release, and retain audit records for 5 years."
)
_AGREEING_TEXT_REWORDED = (
    "Export control compliance requires screening every cross-border shipment against "
    "the denied-parties list prior to release, with audit records kept for five years."
)


@pytest.mark.asyncio
async def test_consensus_reached_when_real_models_genuinely_agree(monkeypatch):
    fakes = {
        "OPENAI": _FakeProvider("OPENAI", text=_AGREEING_TEXT),
        "GEMINI": _FakeProvider("GEMINI", text=_AGREEING_TEXT_REWORDED),
        "GROQ": _FakeProvider("GROQ", fail=True),
        "ANTHROPIC": _FakeProvider("ANTHROPIC", fail=True),
    }
    monkeypatch.setattr(ProviderFactory, "get_provider", classmethod(lambda cls, key, **kw: fakes[key]))

    req = GenerationRequest(prompt="Legal export control audit", persona="LEGAL_COUNSEL", mode="COMPLIANCE_AUDIT")
    res = await MultiLLMConsensusEngine.evaluate_consensus(req)

    assert res.consensus_reached is True
    assert res.agreement_score > 0.75
    assert set(res.participating_providers) == {"OpenAI", "Gemini"}


@pytest.mark.asyncio
async def test_consensus_not_reached_with_only_one_real_responder(monkeypatch):
    """Consensus requires at least 2 independent real answers to cross-validate —
    a single surviving provider must never be reported as 'consensus reached'."""
    fakes = {
        "OPENAI": _FakeProvider("OPENAI", fail=True),
        "GEMINI": _FakeProvider("GEMINI", fail=True),
        "GROQ": _FakeProvider("GROQ", text=_AGREEING_TEXT),
        "ANTHROPIC": _FakeProvider("ANTHROPIC", fail=True),
    }
    monkeypatch.setattr(ProviderFactory, "get_provider", classmethod(lambda cls, key, **kw: fakes[key]))

    req = GenerationRequest(prompt="Legal export control audit", persona="LEGAL_COUNSEL", mode="COMPLIANCE_AUDIT")
    res = await MultiLLMConsensusEngine.evaluate_consensus(req)

    assert res.consensus_reached is False
    assert res.participating_providers == ["Groq"]
    assert "single-model answer" in res.synthesized_payload.text_content.lower()


@pytest.mark.asyncio
async def test_consensus_honest_failure_when_all_providers_fail(monkeypatch):
    fakes = {key: _FakeProvider(key, fail=True) for key in ["OPENAI", "GEMINI", "GROQ", "ANTHROPIC"]}
    monkeypatch.setattr(ProviderFactory, "get_provider", classmethod(lambda cls, key, **kw: fakes[key]))

    req = GenerationRequest(prompt="Legal export control audit", persona="LEGAL_COUNSEL", mode="COMPLIANCE_AUDIT")
    res = await MultiLLMConsensusEngine.evaluate_consensus(req)

    assert res.consensus_reached is False
    assert res.participating_providers == []
    assert "wasn't able to reach any model provider" in res.synthesized_payload.text_content.lower()
