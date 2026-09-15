"""
Real test for the local, free, open-source LLM fallback added 2026-08-21.

This session repeatedly hit genuine, simultaneous quota exhaustion across every
paid provider (OpenAI/Groq/Gemini), with Anthropic/HuggingFace never configured,
leaving zero working models and only a canned "I can't answer" degraded response.
Qwen2.5-0.5B-Instruct (Apache 2.0) now runs directly in-process — same self-hosted
philosophy as BGEEmbedder/the cross-encoder reranker already in this project, not a
new external dependency (transformers + torch were already installed).

Real inference, not a stub — this test asserts on an actual model-generated answer.
"""
import pytest
from app.conversation.providers.factory import LocalTransformersProviderAdapter
from app.conversation.interfaces.llm_provider import GenerationRequest


@pytest.mark.asyncio
async def test_local_provider_gives_a_real_correct_answer():
    provider = LocalTransformersProviderAdapter()
    req = GenerationRequest(
        prompt="What is the capital of France? Answer in one short sentence.",
        raw_query="What is the capital of France?",
        system_prompt="You are a helpful assistant. Be concise and factual.",
        max_tokens=60,
        temperature=0.1,
    )
    res = await provider.generate(req)
    assert "paris" in res.payload.text_content.lower()
    assert res.provider_name == "LocalOSS"
    assert res.cost_usd == 0.0


@pytest.mark.asyncio
async def test_local_is_registered_as_the_final_real_cascade_fallback():
    from app.conversation.runtime.orchestrator import RuntimeOrchestrator
    assert RuntimeOrchestrator._CASCADE_ORDER[-1] == "LOCAL", (
        "LOCAL must stay last in the cascade — paid providers should always be "
        "tried first when actually available."
    )
