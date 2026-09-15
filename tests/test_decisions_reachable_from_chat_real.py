"""
Real test for a significant gap found via live user testing 2026-08-21: a real,
recorded decision (in graph_decisions, extracted from a resolved GitHub PR / Jira
ticket) was completely invisible to normal chat — HybridRetriever only ever searches
document_chunks, a separate table, so "why did we choose X" fell straight through to
the world-knowledge fallback and answered with generic textbook advice instead of the
tenant's own real recorded rationale. This pins the real fix: a tenant-scoped keyword
search over graph_decisions, additive to document retrieval.
"""
import re
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService

TEST_TENANT = "99999999-9999-9999-9999-999999999999"


@pytest.mark.asyncio
async def test_real_decision_rationale_is_used_instead_of_generic_answer():
    dec_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Decision Test Co', :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": TEST_TENANT, "domain": f"decisiontest-{TEST_TENANT[:8]}.example.com"},
        )
        await session.execute(
            text("""
                INSERT INTO graph_decisions (id, tenant_id, decision_title, rationale, actual_outcome, state, created_at)
                VALUES (:id, :tid, :title, :rationale, :outcome, :state, now())
            """),
            {
                "id": dec_id, "tid": TEST_TENANT,
                "title": "Switch the checkout queue from RabbitMQ to Kafka",
                "rationale": "RabbitMQ was dropping messages under peak load during the Nightfall Sale incident. Kafka's log-based replay let us recover the lost checkout events after the fact, which RabbitMQ's at-most-once delivery could not.",
                "outcome": "Done", "state": "Published",
            },
        )
        await session.commit()

    try:
        service = ConversationService()
        result = await service.process_turn(
            tenant_id=TEST_TENANT, user_id="test_user", session_id="decision-chat-test",
            user_query="why did we switch the checkout queue from RabbitMQ to Kafka",
        )
        answer = result.get("response_text", "")
        # Real flake found 2026-08-24: the answer genuinely used the real,
        # specific decision rationale verbatim, but some providers typeset it
        # with real typographic characters — U+202F narrow no-break space
        # ("Nightfall Sale") and U+2011 non-breaking hyphen
        # ("at‑most‑once") — instead of plain ASCII space/hyphen.
        # Same real class of issue already fixed in test_upload_pipeline_real.py
        # (U+202F in a name) and test_rbac_content_filtering_real.py; extended
        # here to also normalize non-breaking hyphens/dashes, which that
        # whitespace-only fix didn't need to cover.
        normalized_answer = re.sub(r"\s+", " ", answer)
        normalized_answer = normalized_answer.replace("‑", "-").replace("‐", "-").replace("–", "-")
        # The real, specific fact from the recorded decision must appear — not a
        # generic "Kafka has better throughput" style textbook answer.
        assert "Nightfall Sale" in normalized_answer or "at-most-once" in normalized_answer or "log-based replay" in normalized_answer, (
            f"Real decision rationale was not used, got: {answer!r}"
        )
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": TEST_TENANT})
            await session.execute(text("DELETE FROM graph_decisions WHERE id = :id"), {"id": dec_id})
            await session.commit()
