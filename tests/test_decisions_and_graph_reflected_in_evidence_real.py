"""
Real bug found via live testing 2026-08-22: a real answer built entirely from a real
recorded decision (its actual rationale text appeared verbatim in the generated
answer, confirmed live) still reported "evidence_used: []" and
"NO_COMPANY_DATA_RETRIEVED" in the explanation ("Why this answer?") panel — a real,
user-visible contradiction with the top-level "grounding" field, which checks the
fuller retrieved context and correctly reported the answer as grounded.

Root cause: ExplanationEngine.generate_explanation() only ever looks at chunks_list
(hybrid_retriever's document chunks) to build evidence_used/reasoning_summary/
grounding_status — decisions and graph relationships/facts were only ever added to
retrieved_texts (the LLM's own prompt content), never to chunks_list, so the
explanation engine had no visibility into them at all.

Fixed by adding a real chunks_list entry whenever a decision or graph
relationship/fact is actually used, so the explanation panel's evidence and
grounding status stay consistent with what real data actually informed the answer.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "88888888-8888-8888-8888-888888888824"


@pytest.mark.asyncio
async def test_decision_only_answer_shows_real_evidence_not_empty():
    decision_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Evidence Gap Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"evidencegaptest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(text("""
            INSERT INTO graph_decisions (id, tenant_id, decision_title, rationale, expected_outcome, actual_outcome, state, created_at)
            VALUES (:id, :t, 'Migrate Zephyr service off legacy queue', 'The legacy queue caused three outages in Q3 2026.', 'Zero message loss', 'In progress', 'in_progress', now())
        """), {"id": decision_id, "t": TEST_TENANT})
        await session.commit()

    try:
        service = ConversationService()
        result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="test_user", session_id="evidence-gap-decision-session",
            user_query="Why are we migrating the Zephyr service off the legacy queue?",
        )
        answer_lower = result.get("response_text", "").lower()
        assert "outage" in answer_lower or "legacy queue" in answer_lower, (
            f"the real decision must actually be used in the answer, got: {answer_lower}"
        )
        explanation = result.get("explanation", {})
        assert explanation.get("evidence_used"), (
            f"a real decision was used to build this answer — evidence_used must not be "
            f"empty, got: {explanation}"
        )
        assert explanation.get("grounding_status") != "NO_COMPANY_DATA_RETRIEVED", (
            f"real company data (a decision) was retrieved and used — grounding_status must "
            f"not claim no company data was found, got: {explanation}"
        )
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM graph_decisions WHERE id = :id"), {"id": decision_id})
            await session.commit()
