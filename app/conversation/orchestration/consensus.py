"""Subsystem 11: Multi-LLM Consensus Engine."""

import asyncio
import math
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel, Field
from app.conversation.interfaces.llm_provider import GenerationRequest, GenerationResponse
from app.conversation.providers.factory import ProviderFactory
from app.conversation.domain.response_payload import MultimodalResponsePayload

# Agreement threshold above which independent models are considered to have reached
# genuine consensus (cosine similarity between their answers' embeddings).
AGREEMENT_THRESHOLD = 0.75

_DISPLAY_NAME = {
    "OPENAI": "OpenAI",
    "GEMINI": "Gemini",
    "GROQ": "Groq",
    "ANTHROPIC": "Anthropic",
}


class ConsensusResult(BaseModel):
    consensus_reached: bool
    agreement_score: float = Field(description="Score between 0.0 and 1.0")
    synthesized_payload: MultimodalResponsePayload
    participating_providers: List[str]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class MultiLLMConsensusEngine:
    """Executes multi-model consensus across the configured real providers (OpenAI, Gemini,
    Groq, Anthropic — whichever have working API keys) for Legal, Finance, Compliance &
    Executive domains.

    Every participating provider makes an independent real call; providers that fail or
    aren't configured are excluded rather than counted as agreeing. Agreement is measured
    by embedding-similarity between the independent answers, not asserted."""

    _CANDIDATES = ["OPENAI", "GEMINI", "GROQ", "ANTHROPIC"]

    @classmethod
    async def evaluate_consensus(cls, request: GenerationRequest) -> ConsensusResult:
        from app.conversation.interfaces.exceptions import LLMProviderOfflineException

        providers = {key: ProviderFactory.get_provider(key) for key in cls._CANDIDATES}
        raw_results = await asyncio.gather(
            *[p.generate(request) for p in providers.values()],
            return_exceptions=True,
        )

        succeeded: List[Tuple[str, GenerationResponse]] = []
        for key, result in zip(providers.keys(), raw_results):
            if isinstance(result, Exception):
                continue
            succeeded.append((key, result))

        if not succeeded:
            return ConsensusResult(
                consensus_reached=False,
                agreement_score=0.0,
                synthesized_payload=MultimodalResponsePayload(
                    text_content=(
                        "I wasn't able to reach any model provider to run a consensus "
                        "check on this request, so I can't give you a verified answer "
                        "right now. Please try again shortly."
                    ),
                    citations=[],
                ),
                participating_providers=[],
            )

        agreement_score = 1.0
        if len(succeeded) >= 2:
            texts = [res.payload.text_content for _, res in succeeded]
            from app.embeddings.bge_embedder import bge_embedder
            vectors = await asyncio.to_thread(bge_embedder.embed_texts, texts)
            sims = [
                _cosine_similarity(vectors[i], vectors[j])
                for i in range(len(vectors))
                for j in range(i + 1, len(vectors))
            ]
            agreement_score = sum(sims) / len(sims) if sims else 1.0

        # Use the most complete real answer as the basis for the synthesized response —
        # not a 120-character truncation of whichever provider happened to run first.
        best_key, best_res = max(succeeded, key=lambda kv: len(kv[1].payload.text_content))
        participating = [key for key, _ in succeeded]
        consensus_reached = len(succeeded) >= 2 and agreement_score >= AGREEMENT_THRESHOLD

        notes = []
        missing = [k for k in cls._CANDIDATES if k not in participating]
        if missing:
            notes.append(f"{', '.join(_DISPLAY_NAME.get(k, k) for k in missing)} did not respond and were excluded from this check.")
        if len(succeeded) == 1:
            notes.append("Only one model responded — this is a single-model answer, not a cross-validated consensus.")
        elif not consensus_reached:
            notes.append(f"Models showed only partial agreement ({agreement_score * 100:.0f}%) — treat this answer with extra scrutiny.")

        synthesized_text = best_res.payload.text_content
        if notes:
            synthesized_text += "\n\n---\n" + "\n".join(f"*{n}*" for n in notes)

        synthesized_payload = MultimodalResponsePayload(
            text_content=synthesized_text,
            citations=best_res.payload.citations,
            suggested_followups=["View model agreement metrics", "Export consensus report"],
        )

        return ConsensusResult(
            consensus_reached=consensus_reached,
            agreement_score=round(agreement_score, 2),
            synthesized_payload=synthesized_payload,
            participating_providers=[_DISPLAY_NAME.get(k, k) for k in participating],
        )
