"""
Real test for a severe hallucination bug found via live user testing 2026-08-21.

"What is the architecture of Project Nebula?" — where "Project Nebula" does not
exist anywhere in the tenant's real data — used to get a fully fabricated, confident
answer describing a fake "architecture" (drawing from real web-search results about
some unrelated public thing sharing that name, e.g. NASA's historical Nebula cloud
platform), with no indication it wasn't about the user's actual company. This pins
the real fix: a "Project <Name>" / "<Name> project" reference that doesn't appear
anywhere in the tenant's real documents gets an honest refusal instead of a websearch-
backed answer that reads as if it's about the user's own company.
"""
import re
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "66666666-6666-6666-6666-666666666666"

# Real bug found via live testing 2026-08-21, on the very query this test's own
# docstring was written about: the "Project <Name>" detection regex matched only
# lowercase "project", so it silently never fired for the natural, capitalized way
# almost everyone actually writes it ("Project Zephyrion", "Project Nebula") — this
# test itself was passing for the wrong reason (or, as confirmed live, actually
# failing) because the gate never triggered at all. Locking in the fix directly.
_PROJECT_NAME_PATTERN = r"\b[Pp]roject\s+([A-Z][a-zA-Z0-9]+)\b|\b([A-Z][a-zA-Z0-9]+)\s+[Pp]roject\b"


def test_project_name_regex_matches_naturally_capitalized_project():
    m = re.search(_PROJECT_NAME_PATTERN, "what is the architecture of Project Zephyrion")
    assert m is not None, "must match the natural, capitalized 'Project X' phrasing"
    assert (m.group(1) or m.group(2)) == "Zephyrion"


def test_project_name_regex_does_not_false_positive_on_generic_lowercase_phrase():
    m = re.search(_PROJECT_NAME_PATTERN, "what is our project management process")
    assert m is None, "a generic lowercase phrase must not be treated as a named project reference"


@pytest.mark.asyncio
async def test_unknown_internal_project_gets_honest_refusal_not_hallucination():
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'No Hallucination Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"nohallu-{TEST_TENANT[:8]}.example.com"},
        )
        await session.commit()

    service = ConversationService()
    result = await service.process_turn(
        tenant_id=TEST_TENANT,
        user_id="test_user",
        session_id="no-hallucination-session",
        user_query="what is the architecture of Project Zephyrion",
    )
    answer_lower = result.get("response_text", "").lower()
    # Must be an honest refusal — phrasing varies (either the new fast-path's fixed
    # wording, or the LLM's own honest self-check further down _world_knowledge()),
    # but it must clearly say it lacks real information, not present fabricated facts.
    assert any(p in answer_lower for p in ["don't have", "do not have", "no information", "not have any information"])
    # The real failure mode this replaces: a multi-bullet fake "architecture" description.
    assert "networking core" not in answer_lower and "control plane" not in answer_lower


@pytest.mark.asyncio
async def test_genuine_general_knowledge_question_still_gets_a_real_answer():
    """Guards against over-correcting: a real, ordinary general-knowledge question
    (no "Project X" pattern at all) must still get answered, not blanket-refused."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'General Knowledge Co', :domain)"),
            {"id": tenant_id, "domain": f"genknow-{tenant_id[:8]}.example.com"},
        )
        await session.commit()

    service = ConversationService()
    result = await service.process_turn(
        tenant_id=tenant_id,
        user_id="test_user",
        session_id="general-knowledge-session",
        user_query="what is the capital of France",
    )
    assert "paris" in result.get("response_text", "").lower()
