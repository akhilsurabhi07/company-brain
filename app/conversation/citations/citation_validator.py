"""Subsystem 13: Sentence-Level Citation Validator.

Validates that every citation attached to an answer actually traces back to a document
that was really retrieved into KnowledgeContext for this turn — catching the common RAG
failure mode of citing a plausible-looking source that was never actually retrieved.
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field


class CitationValidationResult(BaseModel):
    is_valid: bool
    citation_coverage: float = Field(description="Fraction of cited sources actually present in KnowledgeContext (0.0 to 1.0)")
    verified_citations: List[Dict[str, Any]] = Field(default_factory=list)
    invalid_citations: List[str] = Field(default_factory=list)


def _extract_context_text(knowledge_context: Any) -> str:
    if isinstance(knowledge_context, dict):
        return knowledge_context.get("text_content", "") or ""
    if isinstance(knowledge_context, str) and knowledge_context not in (
        "HONEST_REFUSAL_NO_COMPANY_DATA", "KnowledgeContext v1.0.0 Grounded Baseline"
    ):
        return knowledge_context
    return ""


# Citations whose source honestly names the answering provider/engine (not a specific
# company document) aren't a "the AI cited a document" claim to verify against
# KnowledgeContext — they're self-attribution metadata, so they're never "hallucinated".
_SELF_ATTRIBUTION_SOURCES = (
    "openai", "groq", "gemini", "anthropic", "huggingface", "azureopenai",
    "general world knowledge", "general knowledge", "mock",
)


def _is_self_attribution(source: str) -> bool:
    s = source.lower()
    return any(s.startswith(p) or p in s for p in _SELF_ATTRIBUTION_SOURCES)


class CitationValidator:
    """Validates that every citation the model attached to its answer traces back to a
    document that was genuinely part of this turn's retrieved KnowledgeContext."""

    @classmethod
    def validate_citations(
        cls, response_text: str, citations: List[Dict[str, Any]], knowledge_context: Any
    ) -> CitationValidationResult:
        if not citations:
            # Nothing was cited — fine for e.g. general-knowledge or refusal answers;
            # absence of citations isn't itself a validity failure.
            return CitationValidationResult(is_valid=True, citation_coverage=1.0, verified_citations=[])

        context_text = _extract_context_text(knowledge_context).lower()

        verified, invalid = [], []
        for c in citations:
            source = str(c.get("source", "")).strip()
            probe = source.lower()

            if not source or _is_self_attribution(probe):
                # Honest self-attribution ("Groq (...)", "General World Knowledge") isn't a
                # document claim — nothing to verify against KnowledgeContext.
                verified.append(c)
                continue

            if not context_text.strip():
                # A citation claims a specific company document, but nothing was actually
                # retrieved this turn — unverifiable/hallucinated.
                invalid.append(source)
                continue

            # A citation is verifiable if its source title (or a meaningful prefix of it,
            # since models sometimes lightly reformat titles) genuinely appears in the
            # text that was actually retrieved for this turn.
            found = probe in context_text or probe[:15] in context_text
            if found:
                verified.append(c)
            else:
                invalid.append(source)

        coverage = round(len(verified) / len(citations), 3)
        return CitationValidationResult(
            is_valid=len(invalid) == 0,
            citation_coverage=coverage,
            verified_citations=verified,
            invalid_citations=invalid,
        )
