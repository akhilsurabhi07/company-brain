"""
Real bug found 2026-08-22 (surfaced once a real, valid tenant_id let retrieval
run to completion instead of erroring out early on a placeholder string): the
"honest, no company data found — answer from general knowledge" fallback
branch in ConversationService.process_turn() returned a real turn_id but
never called self.timeline.record_turn() — so any query answered this way
(a common path for any brand-new tenant that hasn't uploaded documents yet)
silently broke timeline.replay_turn()/"Execution Timeline" lookups for that
turn, even though the turn_id itself looked completely valid.
"""
import uuid
import pytest
from sqlalchemy import text

from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService
from app.conversation.domain.persona import PersonaType
from app.conversation.domain.modes import ConversationMode


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Timeline WK Test {name_suffix}", "domain": f"timelinewk-{name_suffix}.example.com"},
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
async def test_world_knowledge_fallback_turn_is_replayable():
    """A brand-new tenant with zero documents asking a generic question (no
    'architecture'/'compliance' framing, non-LEGAL_COUNSEL persona) takes the
    honest general-knowledge fallback path — its turn_id must still be a real,
    replayable timeline entry, not a dangling ID the Execution Timeline panel
    can never find anything for."""
    tenant_id = await _make_tenant("wk")
    try:
        service = ConversationService()
        res = await service.process_turn(
            tenant_id=tenant_id, user_id="u1", session_id=None,
            user_query="What is a reasonable way to configure a database cluster?",
            persona=PersonaType.ENGINEER, mode=ConversationMode.ASK,
        )
        turn_id = res["turn_id"]
        assert turn_id, "fallback turn must still carry a real turn_id"

        replayed = service.timeline.replay_turn(turn_id)
        assert replayed is not None, "fallback turns must be recorded in the timeline, not silently skipped"
        assert replayed.turn_id == turn_id
        assert len(replayed.prompt_hash_sha256) == 64
    finally:
        await _cleanup_tenant(tenant_id)
