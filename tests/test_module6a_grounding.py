"""Test Suite 4: Module 6A Grounding, Citation & Safety Tests."""

import pytest
from app.conversation.grounding.grounding_guard import GroundingGuard
from app.conversation.citations.citation_validator import CitationValidator
from app.conversation.validation.output_guard import OutputGuard
from app.conversation.review.response_review import AIResponseReviewEngine
from app.conversation.domain.response_payload import MultimodalResponsePayload

_CONTEXT = {
    "text_content": (
        "Source Document: Project Orion Architectural Specification\n"
        "Content:\nDr. Sarah Lin is the lead engineer and author of the Project Orion "
        "cloud infrastructure architecture. The system uses a multi-region Kubernetes "
        "deployment with automated failover between availability zones."
    )
}


@pytest.mark.asyncio
async def test_grounding_approves_claims_actually_supported_by_context():
    answer = "Dr. Sarah Lin is the lead engineer responsible for the Project Orion cloud infrastructure architecture."
    g_res = await GroundingGuard.verify_grounding(answer, _CONTEXT)
    assert g_res.is_grounded is True
    assert g_res.grounding_score > 0.7
    assert g_res.unsupported_claims == []


@pytest.mark.asyncio
async def test_grounding_rejects_claims_not_in_context():
    answer = "The company's quarterly revenue grew by 45 percent according to the latest board meeting minutes."
    g_res = await GroundingGuard.verify_grounding(answer, _CONTEXT)
    assert g_res.is_grounded is False
    assert g_res.unsupported_claims != []


@pytest.mark.asyncio
async def test_grounding_rejects_a_claim_that_inverts_the_source_documents_negation():
    # Real bug found via live AI-quality testing 2026-08-23: uploaded a real
    # document stating a stipend "does NOT cover furniture purchases over
    # $200 (those require separate manager approval)". The model answered
    # "Yes, the stipend covers furniture purchases over $200" — the opposite
    # claim — and this guard scored it grounding_score=1.00, "Grounded in
    # your data, Confidence: 100%". Pure embedding-cosine similarity cannot
    # represent negation: "X covers Y" and "X does not cover Y" share every
    # content word and sit almost on top of each other in embedding space.
    stipend_context = {
        "text_content": (
            "The stipend does NOT cover: personal internet/mobile phone bills, "
            "coffee, or furniture purchases over $200 (those require separate "
            "manager approval via the Capital Expense process)."
        )
    }
    inverted_answer = "Yes, the stipend covers furniture purchases over $200."
    g_res = await GroundingGuard.verify_grounding(inverted_answer, stipend_context)
    assert g_res.is_grounded is False, (
        f"a claim that inverts the source's negation must not be scored as grounded, got: {g_res}"
    )
    assert g_res.unsupported_claims != []

    # The correctly-phrased (non-inverted) claim must still pass — this is a
    # polarity check, not a ban on the topic or the word "furniture".
    correct_answer = "No, the stipend does not cover furniture purchases over $200."
    g_res_correct = await GroundingGuard.verify_grounding(correct_answer, stipend_context)
    assert g_res_correct.is_grounded is True, (
        f"a claim matching the source's real negation must still pass, got: {g_res_correct}"
    )


@pytest.mark.asyncio
async def test_grounding_flags_wrong_document_via_entity_mismatch():
    """If the query names a specific 'Project X' that never appears anywhere in what was
    actually retrieved, that's likely wrong-document retrieval — even if the retrieved
    text is topically similar enough that per-sentence similarity alone might pass it."""
    answer = "The lead engineer for this project is Dr. Sarah Lin, who designed the cloud infrastructure architecture."
    g_res = await GroundingGuard.verify_grounding(answer, _CONTEXT, user_query="who leads Project Zephyr")
    assert g_res.is_grounded is False
    assert "zephyr" in [c.lower() for c in g_res.unsupported_claims]


@pytest.mark.asyncio
async def test_grounding_honest_refusal_is_not_penalized():
    g_res = await GroundingGuard.verify_grounding(
        "I couldn't find this information in your company's data.", "HONEST_REFUSAL_NO_COMPANY_DATA"
    )
    assert g_res.is_grounded is True


def test_citation_validator_accepts_real_retrieved_source():
    c_res = CitationValidator.validate_citations(
        "Answer text",
        [{"citation_id": "1", "source": "Project Orion Architectural Specification"}],
        _CONTEXT,
    )
    assert c_res.is_valid is True
    assert c_res.citation_coverage == 1.0
    assert c_res.invalid_citations == []


def test_citation_validator_flags_fabricated_source():
    c_res = CitationValidator.validate_citations(
        "Answer text",
        [{"citation_id": "1", "source": "A Document That Was Never Retrieved"}],
        _CONTEXT,
    )
    assert c_res.is_valid is False
    assert "A Document That Was Never Retrieved" in c_res.invalid_citations


def test_review_engine_rejects_untruncated_but_ungrounded_response():
    payload = MultimodalResponsePayload(text_content="This is a complete sentence with no issues.", citations=[])
    review = AIResponseReviewEngine.review_response(payload, "ASK", grounding_score=0.1, citation_coverage=0.0)
    assert review.is_approved is False


def test_review_engine_approves_well_grounded_complete_response():
    payload = MultimodalResponsePayload(text_content="This is a well-grounded, complete answer.", citations=[])
    review = AIResponseReviewEngine.review_response(payload, "ASK", grounding_score=1.0, citation_coverage=1.0)
    assert review.is_approved is True
    assert review.quality_score >= 0.9


def test_output_safety_guard():
    raw = "Here is the key: sk_live_99887766554433221100"
    sanitized, ok = OutputGuard.sanitize_output(raw)

    assert "sk_live_" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
    assert ok is True
