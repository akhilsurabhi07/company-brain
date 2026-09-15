"""Subsystem 12: Grounding Guard Engine.

Verifies that the model's generated claims are actually supported by the KnowledgeContext
that was really retrieved for this turn — via embedding-similarity between each answer
sentence and the retrieved content — rather than asserting groundedness unconditionally.
"""

import asyncio
import re
from typing import Any, List
from pydantic import BaseModel, Field


class GroundingCheckResult(BaseModel):
    is_grounded: bool
    grounding_score: float = Field(description="Score between 0.0 and 1.0")
    unsupported_claims: list = Field(default_factory=list)
    reasoning: str = ""


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_HONEST_REFUSAL_MARKERS = (
    "wasn't able to find", "couldn't find", "don't have", "no information",
    # RuntimeOrchestrator's / MultiLLMConsensusEngine's all-providers-failed degraded
    # responses ("...wasn't able to reach any [AI model|model] provider...").
    "wasn't able to reach",
)

# Real bug found via live AI-quality testing 2026-08-23: a real uploaded document
# said a stipend "does NOT cover furniture purchases over $200"; the model
# answered "Yes, the stipend covers furniture purchases over $200" — the exact
# opposite claim — and this guard scored it grounding_score=1.00, "Grounded in
# your data, Confidence: 100%". Root cause: pure embedding-cosine similarity has
# no way to represent negation — "X covers Y" and "X does not cover Y" sit
# almost on top of each other in embedding space, since they share every content
# word. This is not a full fix (that needs real NLI/entailment, not a keyword
# list) but it catches exactly this failure mode and the broader class it
# represents: a topically-supported claim whose negation polarity disagrees
# with its best-matching source sentence is a contradiction, not a match.
_NEGATION_MARKERS = (
    " not ", "n't ", " never ", " no longer ", " cannot ", " excludes ",
    " excluding ", " without ", " won't ", " will not ", " unable to ",
)


def _has_negation(text: str) -> bool:
    t = f" {text.lower()} "
    return any(m in t for m in _NEGATION_MARKERS)


def _extract_context_text(knowledge_context: Any) -> str:
    if isinstance(knowledge_context, dict):
        return knowledge_context.get("text_content", "") or ""
    if isinstance(knowledge_context, str) and knowledge_context not in (
        "HONEST_REFUSAL_NO_COMPANY_DATA", "KnowledgeContext v1.0.0 Grounded Baseline"
    ):
        return knowledge_context
    return ""


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class GroundingGuard:
    """Real embedding-based grounding check against the actually-retrieved KnowledgeContext."""

    SUPPORT_THRESHOLD = 0.55  # BGE cosine similarity below this = likely unsupported claim
    MIN_CLAIM_LEN = 25  # shorter sentences are usually connective/framing text, not claims
    APPROVAL_THRESHOLD = 0.7

    @classmethod
    async def verify_grounding(
        cls, response_text: str, knowledge_context: Any, user_query: str = "",
        require_company_grounding: bool = True,
    ) -> GroundingCheckResult:
        if not response_text:
            return GroundingCheckResult(is_grounded=False, grounding_score=0.0, reasoning="Empty response.")

        context_text = _extract_context_text(knowledge_context)

        # Named-entity sanity check: if the user asked about a specific "Project X" and X
        # never appears anywhere in what was actually retrieved, the retrieval likely pulled
        # the wrong (but topically similar) document — a per-sentence similarity check alone
        # can still pass in that case since the wrong document may use similar vocabulary.
        if user_query and context_text.strip():
            project_mentions = set(m.lower() for m in re.findall(r"\bproject\s+([a-zA-Z0-9]+)", user_query, re.IGNORECASE))
            missing = [p for p in project_mentions if p not in context_text.lower()]
            if missing:
                return GroundingCheckResult(
                    is_grounded=False, grounding_score=0.0, unsupported_claims=list(missing),
                    reasoning=f"Query referenced {missing}, but retrieved KnowledgeContext contains no mention of it — likely wrong-document retrieval.",
                )

        if not context_text.strip():
            # No retrieved company context to verify against. An honest refusal isn't a
            # fabrication, so don't flag it as ungrounded; anything else claiming company
            # facts with nothing behind it genuinely can't be verified.
            if any(m in response_text.lower() for m in _HONEST_REFUSAL_MARKERS):
                return GroundingCheckResult(
                    is_grounded=True, grounding_score=1.0,
                    reasoning="Honest refusal — no company-data claims to verify.",
                )
            if not require_company_grounding:
                # Consensus / expert-knowledge turns (Legal, Finance, CEO) legitimately
                # answer from the model's own professional expertise rather than retrieved
                # company documents — that's not a fabrication signal by itself, so don't
                # reject it the way a normal RAG-mode "no context, confident answer" would be.
                return GroundingCheckResult(
                    is_grounded=True, grounding_score=0.8,
                    reasoning="No company KnowledgeContext was applicable — treated as a general/expert-knowledge answer, not verified against company documents.",
                )
            return GroundingCheckResult(
                is_grounded=False, grounding_score=0.0,
                reasoning="No retrieved KnowledgeContext was available to verify this answer's claims against.",
            )

        claims = [s.strip() for s in _SENTENCE_SPLIT_RE.split(response_text) if len(s.strip()) >= cls.MIN_CLAIM_LEN]
        if not claims:
            return GroundingCheckResult(is_grounded=True, grounding_score=1.0, reasoning="No substantive claims to verify.")

        from app.embeddings.bge_embedder import bge_embedder
        context_chunks = [c.strip() for c in context_text.split("\n\n") if c.strip()] or [context_text]

        claim_vecs, context_vecs = await asyncio.to_thread(
            lambda: (bge_embedder.embed_texts(claims), bge_embedder.embed_texts(context_chunks))
        )

        unsupported = []
        supported_count = 0
        for claim, cvec in zip(claims, claim_vecs):
            sims = [_cosine(cvec, ctxvec) for ctxvec in context_vecs]
            best_idx = max(range(len(sims)), key=lambda i: sims[i])
            best = sims[best_idx]
            if best >= cls.SUPPORT_THRESHOLD:
                # Real bug found via live testing 2026-08-31: this used to compare the
                # claim's negation polarity against the polarity of the ENTIRE matched
                # chunk, not the specific sentence within it that actually supports the
                # claim. A chunk with multiple sentences of different polarity (e.g. "X
                # is $150/month. X does not cover Y.") made every claim matched against
                # that chunk inherit a false "contains negation" signal from an
                # unrelated sentence elsewhere in the same chunk -- a correct, plain
                # claim like "$150 per month" was wrongly flagged "negation/polarity
                # mismatch" and shown to the user as "Not grounded, 30% confident"
                # despite being exactly right and directly cited. Fixed by checking
                # polarity against the single best-matching SENTENCE inside the
                # winning chunk, not the whole chunk.
                best_chunk = context_chunks[best_idx]
                chunk_sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(best_chunk) if s.strip()]
                if len(chunk_sentences) > 1:
                    sent_vecs = await asyncio.to_thread(bge_embedder.embed_texts, chunk_sentences)
                    sent_sims = [_cosine(cvec, svec) for svec in sent_vecs]
                    best_sentence = chunk_sentences[max(range(len(sent_sims)), key=lambda i: sent_sims[i])]
                else:
                    best_sentence = best_chunk
                if _has_negation(claim) != _has_negation(best_sentence):
                    unsupported.append(claim[:160] + " [negation/polarity mismatch with the closest matching source text]")
                else:
                    supported_count += 1
            else:
                unsupported.append(claim[:160])

        grounding_score = round(supported_count / len(claims), 3)
        return GroundingCheckResult(
            is_grounded=grounding_score >= cls.APPROVAL_THRESHOLD,
            grounding_score=grounding_score,
            unsupported_claims=unsupported,
            reasoning=(
                f"{supported_count}/{len(claims)} claim(s) matched retrieved KnowledgeContext "
                f"content (similarity >= {cls.SUPPORT_THRESHOLD})."
            ),
        )
