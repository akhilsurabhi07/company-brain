"""
Shared RBAC/ABAC sentence-level content redaction.

Extracted 2026-08-22 from a closure that lived only inside
`ConversationService.process_turn()` — every place that surfaces
decisions/facts/relationships to a non-admin caller needs this exact same
policy, and the new Decisions/Risks read endpoints (app/api/graph_api.py)
are a second, independent caller of it. Duplicating the closure would risk
a repeat of the real bug found 2026-08-22 (Module 4 integration): decisions
and graph content added to a response AFTER a redaction filter had already
run were never subject to it at all, and a non-admin extracted real salary
figures verbatim as a result. One shared function, one place to get it
right.

Policy: sentence-level redaction, not whole-record dropping — a document/
decision mixing a legitimate fact (leave days) with a restricted one
(salary) in the same block must still surface the legitimate part.
"""
import re
from typing import Optional

RESTRICTED_TERMS = ("salary", "payroll", "compensation", "bonus")


def redact_if_restricted(text_in: str, caller_role: str) -> Optional[str]:
    """Returns `text_in` unchanged for admins. For anyone else, strips out
    only the sentences/lines containing a restricted term, keeping the rest
    intact. Returns None only if every sentence was restricted."""
    if caller_role == "admin":
        return text_in
    # Split on sentence boundaries AND newlines — decisions/facts are often
    # built as "Title\nOutcome: ...\nRationale: ..." blocks with no terminal
    # punctuation between fields; a plain sentence-boundary split would treat
    # the whole multi-field block as one unsplittable "sentence".
    sentences = re.split(r"(?<=[.!?])\s+|\n", text_in)
    kept = [s for s in sentences if not any(term in s.lower() for term in RESTRICTED_TERMS)]
    if not kept:
        return None  # every sentence was restricted — drop entirely
    joiner = "\n" if "\n" in text_in else " "
    if len(kept) < len(sentences):
        kept.append("[Some content in this source was withheld — restricted to admins.]")
    return joiner.join(kept)
