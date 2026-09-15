"""
CRITICAL real security bug found via live testing 2026-08-22, introduced by wiring
decisions and graph facts/relationships into the live chat context (Module 4
integration): they were added AFTER the RBAC content filter had already run over
document chunks, so they were never subject to it at all.

Confirmed live and exploitable: a real recorded decision titled "Approve Q3
engineering salary increase" (rationale: "Senior engineer salary was raised 12
percent to 22 lakhs per annum...") was fully readable by a non-admin test account,
who successfully extracted the exact "12%" and "22 lakhs per annum" figures verbatim
by asking a direct question. Fixed by applying the same sentence-level RBAC
redaction used for document chunks to decisions and graph facts/relationships
before they're added to the live context, for every non-admin caller.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "88888888-8888-8888-8888-888888888825"


@pytest.mark.asyncio
async def test_member_never_sees_a_salary_decisions_real_figures():
    decision_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'RBAC Decision Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"rbacdecisiontest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(text("""
            INSERT INTO graph_decisions (id, tenant_id, decision_title, rationale, expected_outcome, actual_outcome, state, created_at)
            VALUES (:id, :t, 'Approve Q3 engineering salary increase', 'Senior engineer salary was raised 12 percent to 22 lakhs per annum to match market compensation and reduce attrition.', 'Reduce attrition', 'Approved', 'completed', now())
        """), {"id": decision_id, "t": TEST_TENANT})
        await session.commit()

    try:
        service = ConversationService()
        admin_result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="admin_user", session_id="rbac-decision-admin-session",
            user_query="By what percentage was the Q3 engineering salary increased, and to what new amount?",
            caller_role="admin",
        )
        admin_answer = admin_result.get("response_text", "").lower()
        assert "12" in admin_answer or "22 lakh" in admin_answer, f"admin should see the real figures, got: {admin_answer}"

        member_result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="member_user", session_id="rbac-decision-member-session",
            user_query="By what percentage was the Q3 engineering salary increased, and to what new amount?",
            caller_role="member",
        )
        member_answer = member_result.get("response_text", "").lower()
        assert "22 lakh" not in member_answer, (
            f"CRITICAL: non-admin must never see the real restricted salary figure "
            f"from a decision, got: {member_answer}"
        )
        assert "12 percent" not in member_answer and "12%" not in member_answer, (
            f"CRITICAL: non-admin must never see the real restricted raise percentage "
            f"from a decision, got: {member_answer}"
        )
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM graph_decisions WHERE id = :id"), {"id": decision_id})
            await session.commit()
