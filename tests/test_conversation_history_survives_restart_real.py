"""
Module 6B — real durable conversation history (2026-08-22).

Before this, ConversationService held all session/turn history in
InMemorySessionRepository — a plain Python dict inside one process. A
server restart, crash, or any multi-instance/horizontal-scaling deployment
silently wiped every tenant's entire conversation history. Fixed with
PostgresSessionRepository, a real, RLS-protected, drop-in replacement.

These tests exercise the repository directly (not through a real LLM call)
so they stay fast and deterministic; a fresh ConversationService() instance
is constructed for the "after restart" step specifically because the old
in-memory version would have failed this exact test (a new instance means a
brand new, empty dict) while the new one must not.
"""
import uuid
import pytest
from sqlalchemy import text

from app.db.database import async_session_factory
from app.conversation.session.postgres_repo import PostgresSessionRepository
from app.conversation.domain.context import ConversationSession, ConversationTurn
from app.conversation.domain.states import SessionState
from app.conversation.domain.persona import PersonaType
from app.conversation.domain.modes import ConversationMode
from app.conversation.domain.response_payload import MultimodalResponsePayload


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Session Persist Test {name_suffix}", "domain": f"sesspersist-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_turns WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_sessions WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_session_and_turn_survive_a_fresh_repository_instance():
    """Simulates a server restart: a brand-new PostgresSessionRepository()
    instance (no shared in-process state at all with the one that wrote the
    data) must still see the real, previously-written session and turn."""
    tenant_id = await _make_tenant("restart")
    try:
        repo_before_restart = PostgresSessionRepository()
        session = ConversationSession(tenant_id=tenant_id, user_id="u1", title="Real onboarding question")
        session.state = SessionState.ACTIVE
        await repo_before_restart.create_session(session)

        turn = ConversationTurn(
            session_id=session.session_id, user_query="What is our VPN policy?",
            persona_used=PersonaType.ENGINEER, mode_used=ConversationMode.ASK,
            assistant_response=MultimodalResponsePayload(text_content="Use GlobalProtect.", citations=[]),
            model_name="groq-test", latency_ms=42.0, cost_usd=0.0,
        )
        await repo_before_restart.add_turn(session.session_id, turn, tenant_id)

        # "Restart": a brand-new repository object, zero shared Python state.
        repo_after_restart = PostgresSessionRepository()
        restored = await repo_after_restart.get_session(session.session_id, tenant_id)

        assert restored is not None, "session must survive a fresh repository instance"
        assert restored.title == "Real onboarding question"
        assert len(restored.turns) == 1
        assert restored.turns[0].user_query == "What is our VPN policy?"
        assert restored.turns[0].assistant_response.text_content == "Use GlobalProtect."
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_get_session_rejects_cross_tenant_session_id():
    """Real security check on the new repository: a session_id that exists
    but belongs to a different tenant must not be returned just because the
    ID was guessed/known — same real-world exploit class the rest of this
    engagement has closed everywhere else."""
    tenant_a = await _make_tenant("sess-a")
    tenant_b = await _make_tenant("sess-b")
    try:
        repo = PostgresSessionRepository()
        session = ConversationSession(tenant_id=tenant_a, user_id="u1", title="Tenant A's private conversation")
        session.state = SessionState.ACTIVE
        await repo.create_session(session)

        cross_tenant_result = await repo.get_session(session.session_id, tenant_b)
        assert cross_tenant_result is None
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
