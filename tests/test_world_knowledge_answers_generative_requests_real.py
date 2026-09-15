"""
Real bug found via live browser testing 2026-08-22: a brand-new tenant with
zero uploaded documents asked "Write a short python function that adds two
numbers, in a code block." and got "I don't have that information in the
provided context." — a false refusal for a purely generative/coding request
that has nothing to do with company data at all.

Root cause: `_world_knowledge()`'s Tier 1.5 (Groq search-context synthesis)
is instructed to answer "using ONLY the search context provided" — correct
for a genuine fact-lookup question, but there's no relevant web search
context for a code-generation request, so it correctly (by its own
instructions) refuses. That refusal was returned as the function's final
answer instead of falling through to Tier 2/3/4 (direct, unconstrained model
calls) that can actually write two lines of Python. Fixed by detecting a
refusal-shaped response from Tier 1.5/2 and falling through instead of
returning it as final.
"""
import pytest
from app.agents.orchestrator import _world_knowledge, _looks_like_refusal


def test_looks_like_refusal_detects_known_phrasings():
    assert _looks_like_refusal("I don't have that information in the provided context.")
    assert _looks_like_refusal("I couldn't find this information in your company's data.")
    assert not _looks_like_refusal("def add(a, b):\n    return a + b")


def test_looks_like_refusal_treats_blank_completion_as_a_refusal():
    # Real bug found via live browser testing 2026-08-23: a fresh tenant asking
    # a purely generative markdown/code-formatting question got a chat bubble
    # showing the raw internal JSON envelope with an EMPTY text_content instead
    # of a real answer. Root cause: one provider tier returned HTTP 200 with a
    # blank/whitespace-only completion body (a real, observed LLM API edge
    # case — content filtering or a zero-token generation) and
    # _looks_like_refusal("") returned False (no known phrase is a substring
    # of ""), so the blank text was accepted as that tier's final answer
    # instead of falling through to the next tier. Blank/whitespace-only text
    # must be treated exactly like an explicit refusal.
    assert _looks_like_refusal("")
    assert _looks_like_refusal("   ")
    assert _looks_like_refusal("\n\t ")


def test_looks_like_refusal_detects_smart_quote_apostrophes():
    # Real bug found 2026-08-22: models sometimes typeset the apostrophe as
    # U+2019 (right single quotation mark) instead of a plain ASCII U+0027 —
    # the exact phrasing observed live from both Groq and the local model.
    # The substring check silently failed to match it, so the refusal went
    # undetected and was returned as a final answer regardless of the
    # fallthrough logic this whole file is about.
    smart_quote_refusal = "I don" + chr(0x2019) + "t have that information in the provided context."
    assert _looks_like_refusal(smart_quote_refusal), (
        f"must detect a refusal even with a Unicode smart-quote apostrophe, got: {smart_quote_refusal!r}"
    )


@pytest.mark.asyncio
async def test_world_knowledge_answers_a_real_coding_request_not_a_refusal():
    answer = await _world_knowledge("Write a short python function that adds two numbers, in a code block.")
    assert not _looks_like_refusal(answer), f"generative coding request must not fall back to a refusal, got: {answer}"
    lowered = answer.lower()
    assert "def " in lowered or "return" in lowered, f"expected an actual python function in the answer, got: {answer}"
