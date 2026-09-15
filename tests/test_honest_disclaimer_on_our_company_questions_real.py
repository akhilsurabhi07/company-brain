"""
Real trust gap found via live testing 2026-08-22: a question phrased as a claim
about the user's own company ("Is customer data properly isolated between our
different customers in the database?") that finds no real company data falls to
the general-knowledge fallback — which confidently answers "Yes, ..." with generic
textbook advice, phrased exactly like it's describing the user's real, verified
system. The "Why this answer?" panel does honestly disclose NO_COMPANY_DATA_RETRIEVED,
but the chat bubble text itself reads as an assertion about their actual setup
unless the user clicks through to check.

Fixed by prepending an explicit disclaimer to the chat bubble text itself whenever
a query uses "our/we/us" phrasing and no real company data was found.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "88888888-8888-8888-8888-888888888813"


@pytest.mark.asyncio
async def test_our_company_question_with_no_real_data_gets_an_explicit_disclaimer():
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Disclaimer Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"disclaimertest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.commit()

    service = ConversationService()
    result = await service.process_turn(
        tenant_id=TEST_TENANT, user_id="test_user", session_id="disclaimer-test-session",
        user_query="Is customer data properly isolated between our different customers in the database?",
    )
    answer_lower = result.get("response_text", "").lower()
    assert "specific, verified information about your organization's actual setup" in answer_lower, (
        f"a claim-shaped question about 'our' company with no real data found must "
        f"carry an explicit disclaimer in the chat bubble itself, got: {answer_lower}"
    )


@pytest.mark.asyncio
async def test_genuine_general_knowledge_question_is_not_over_disclaimed():
    """Guards against over-correcting: an ordinary general-knowledge question with
    no 'our/we/us' phrasing must not get the disclaimer prepended."""
    tenant_id = "88888888-8888-8888-8888-888888888814"
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'No Disclaimer Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "domain": f"nodisclaimertest-{tenant_id[:8]}.example.com"},
        )
        await session.commit()

    service = ConversationService()
    result = await service.process_turn(
        tenant_id=tenant_id, user_id="test_user", session_id="no-disclaimer-test-session",
        user_query="What is the capital of Australia?",
    )
    answer_lower = result.get("response_text", "").lower()
    assert "specific, verified information about your organization's actual setup" not in answer_lower
