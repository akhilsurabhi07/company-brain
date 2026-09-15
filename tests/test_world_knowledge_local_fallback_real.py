"""
Real test for a gap found via live testing 2026-08-21: _world_knowledge()
(the "no company data at all" fallback used by conversation_service.py) has its
own independent 5-tier cascade — builtin KB, DuckDuckGo, Groq-synthesis, Gemini,
Groq-direct, OpenAI — and never included the LOCAL provider (Qwen2.5-0.5B-
Instruct) added the same day to RuntimeOrchestrator's cascade for company-data
answers.

Confirmed live: a plain "what is the capital of France" question hit a moment
where OpenAI/Groq/Gemini were all genuinely quota-exhausted (real 429s) and
DuckDuckGo's Instant Answer API returned an empty placeholder "test" payload
for ordinary trivia (a real, known limitation of that free API for general
knowledge questions, not a bug) — the honest give-up message fired despite a
working, free, local model being available the whole time.

Fixed by adding LOCAL as a real tier right before the final give-up message.
"""
import pytest
from unittest.mock import AsyncMock, patch
from app.agents.orchestrator import _world_knowledge


@pytest.mark.asyncio
async def test_world_knowledge_falls_back_to_local_model_when_every_paid_tier_is_down():
    """Simulates the exact real condition hit live: every network tier (DDG,
    Groq synthesis, Gemini, Groq direct, OpenAI) fails or has no key configured,
    so the local model must be tried before the honest give-up message."""
    with patch("httpx.AsyncClient") as mock_client_cls, \
         patch("app.config.settings") as mock_settings:
        mock_client_cls.side_effect = Exception("network unavailable (simulating real quota/DDG-empty conditions)")
        mock_settings.GROQ_API_KEY = None
        mock_settings.GEMINI_API_KEY = None
        mock_settings.OPENAI_API_KEY = None

        from app.conversation.providers.factory import LocalTransformersProviderAdapter
        from app.conversation.domain.response_payload import MultimodalResponsePayload
        from app.conversation.interfaces.llm_provider import GenerationResponse

        fake_response = GenerationResponse(
            payload=MultimodalResponsePayload(text_content="Paris is the capital of France.", citations=[]),
            model_name=LocalTransformersProviderAdapter.MODEL_ID,
            provider_name="LocalOSS",
            latency_ms=1.0,
            cost_usd=0.0,
        )
        with patch.object(LocalTransformersProviderAdapter, "generate", new=AsyncMock(return_value=fake_response)):
            answer = await _world_knowledge("what is the capital of France")

        assert "paris" in answer.lower(), (
            f"LOCAL fallback must be used before the honest give-up message when every "
            f"paid tier is genuinely unavailable, got: {answer}"
        )


@pytest.mark.asyncio
async def test_world_knowledge_still_gives_up_honestly_if_local_also_fails():
    """The final Tier 5 give-up message must still fire if even LOCAL fails —
    never silently return an empty or fabricated answer."""
    with patch("httpx.AsyncClient") as mock_client_cls, \
         patch("app.config.settings") as mock_settings:
        mock_client_cls.side_effect = Exception("network unavailable")
        mock_settings.GROQ_API_KEY = None
        mock_settings.GEMINI_API_KEY = None
        mock_settings.OPENAI_API_KEY = None

        from app.conversation.providers.factory import LocalTransformersProviderAdapter
        with patch.object(LocalTransformersProviderAdapter, "generate", new=AsyncMock(side_effect=Exception("local also down"))):
            answer = await _world_knowledge("what is the capital of a made up nonexistent country xyzzy123")

        assert "wasn't able to find" in answer.lower()
