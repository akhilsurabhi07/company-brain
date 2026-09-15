"""Subsystem 17: Explanation Engine.

Fixed 2026-08-20: this was a hardcoded stub — confidence_score always 0.984,
grounding_status always "VERIFIED_GROUNDED", evidence_used always a fake single
"doc_001"/"KnowledgeContext v1" entry, reasoning_summary a canned sentence claiming
"passed zero-hallucination verification" regardless of whether that was true. It also
had zero live callers (dead code) despite conversation_service.py already computing
everything real needed to answer "why this answer" (GroundingGuard, CitationValidator,
AIResponseReviewEngine results, and the actual retrieved chunks) — this was the exact
source of the frontend's hardcoded "98.4% / PASSED" panel (same number, not a
coincidence). Now takes those real results directly and reflects them honestly,
including the case where grounding genuinely failed or nothing was retrieved.
"""

from typing import Dict, Any, List
from pydantic import BaseModel, Field


class ExplanationPayload(BaseModel):
    user_query: str
    reasoning_summary: str
    evidence_used: List[Dict[str, Any]] = Field(default_factory=list)
    confidence_score: float
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    grounding_status: str


class ExplanationEngine:
    """Builds a transparent, real explanation from this turn's actual grounding/
    citation/review results and retrieved chunks — never a fixed template."""

    @classmethod
    def generate_explanation(
        cls,
        user_query: str,
        response_payload: Any,
        grounding_res: Any,
        citation_res: Any,
        review_res: Any,
        chunks: List[Dict[str, Any]],
    ) -> ExplanationPayload:
        citations = getattr(response_payload, "citations", []) or []

        evidence_used = [
            {
                "doc_title": c.get("doc_title", "Untitled"),
                "source_app": c.get("source_app", "unknown"),
                "rerank_score": c.get("score"),
            }
            for c in (chunks or [])
        ]

        grounding_status = "VERIFIED_GROUNDED" if getattr(grounding_res, "is_grounded", False) else "NOT_GROUNDED"
        if not chunks:
            grounding_status = "NO_COMPANY_DATA_RETRIEVED"

        if not chunks:
            reasoning_summary = (
                "No company documents were retrieved as relevant for this query, so the answer "
                "either came from general knowledge or is an honest refusal — it was not verified "
                "against your organization's data."
            )
        elif getattr(grounding_res, "is_grounded", False):
            reasoning_summary = (
                f"Retrieved {len(chunks)} real passage(s) from your organization's data. "
                f"Grounding check passed (score {getattr(grounding_res, 'grounding_score', 0):.2f}) — "
                f"the answer's claims were verified against what was actually retrieved, not assumed."
            )
        else:
            unsupported = getattr(grounding_res, "unsupported_claims", None) or []
            reasoning_summary = (
                f"Retrieved {len(chunks)} passage(s), but the grounding check found claims not "
                f"supported by them (score {getattr(grounding_res, 'grounding_score', 0):.2f})"
                + (f" — unsupported: {'; '.join(unsupported[:3])}" if unsupported else "") + "."
            )

        confidence_score = round(
            0.5 * getattr(grounding_res, "grounding_score", 0.0) + 0.5 * getattr(review_res, "quality_score", 0.0),
            3,
        )

        return ExplanationPayload(
            user_query=user_query,
            reasoning_summary=reasoning_summary,
            evidence_used=evidence_used,
            confidence_score=confidence_score,
            citations=citations,
            grounding_status=grounding_status,
        )
