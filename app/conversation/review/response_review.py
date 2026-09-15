"""Subsystem 14: AI Response Review Engine.

The final quality gate: combines the real grounding and citation-coverage signals with
real completeness/formatting checks on the response text into one composite quality score
and approval decision — rather than approving every non-empty response unconditionally.
"""

from typing import List
from pydantic import BaseModel, Field
from app.conversation.domain.response_payload import MultimodalResponsePayload

APPROVAL_THRESHOLD = 0.6


class ReviewResult(BaseModel):
    is_approved: bool
    quality_score: float = Field(description="Score between 0.0 and 1.0")
    completeness_check: bool = True
    formatting_check: bool = True
    missing_sections: List[str] = Field(default_factory=list)
    rejection_reason: str = ""


class AIResponseReviewEngine:
    """Reviews a generated response for completeness, formatting, and (via the caller-supplied
    grounding/citation scores) unsupported or unverifiable claims."""

    @classmethod
    def review_response(
        cls,
        payload: MultimodalResponsePayload,
        mode: str,
        grounding_score: float = 1.0,
        citation_coverage: float = 1.0,
    ) -> ReviewResult:
        text = payload.text_content or ""
        stripped = text.strip()

        if not stripped or len(stripped) < 10:
            return ReviewResult(
                is_approved=False,
                quality_score=0.2,
                completeness_check=False,
                rejection_reason="Response content is incomplete or empty.",
            )

        missing_sections: List[str] = []

        # Completeness: does the response look like it was cut off mid-thought?
        completeness_check = True
        if stripped[-1] not in ".!?\"'`)]}】*" and not stripped.endswith("```"):
            completeness_check = False
            missing_sections.append("response appears truncated (no closing punctuation)")

        # Formatting: are markdown constructs the model used actually balanced?
        formatting_check = True
        if stripped.count("```") % 2 != 0:
            formatting_check = False
            missing_sections.append("unclosed code block")
        if stripped.count("**") % 2 != 0:
            formatting_check = False
            missing_sections.append("unbalanced bold markers")

        # Composite score: grounding and citation trust matter most, completeness/formatting
        # are secondary quality signals.
        quality_score = round(
            0.4 * max(0.0, min(grounding_score, 1.0))
            + 0.3 * max(0.0, min(citation_coverage, 1.0))
            + 0.15 * (1.0 if completeness_check else 0.0)
            + 0.15 * (1.0 if formatting_check else 0.0),
            3,
        )

        is_approved = quality_score >= APPROVAL_THRESHOLD and completeness_check
        rejection_reason = ""
        if not is_approved:
            reasons = missing_sections or [f"composite quality score {quality_score} below threshold {APPROVAL_THRESHOLD}"]
            rejection_reason = "Quality review failed: " + "; ".join(reasons)

        return ReviewResult(
            is_approved=is_approved,
            quality_score=quality_score,
            completeness_check=completeness_check,
            formatting_check=formatting_check,
            missing_sections=missing_sections,
            rejection_reason=rejection_reason,
        )
