"""Real, durable PostgreSQL Session Repository — Module 6B (2026-08-22).

Before this, ConversationService held all session/turn history in
InMemorySessionRepository — a plain Python dict inside one process. A
server restart, crash, or any multi-instance/horizontal-scaling deployment
silently wiped or fragmented every tenant's entire conversation history,
with no way to recover it and no way to build "Project memory... revisitable
months later" (the vision's own words) on top of it. This is a drop-in
replacement implementing the exact same BaseSessionRepository interface, so
ConversationService's own logic doesn't need to change — only which
repository it's constructed with.
"""
import json
from typing import List, Optional
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.domain.context import ConversationSession, ConversationTurn
from app.conversation.domain.states import SessionState
from app.conversation.domain.response_payload import MultimodalResponsePayload
from app.conversation.interfaces.session_interface import BaseSessionRepository


class PostgresSessionRepository(BaseSessionRepository):
    """Real, tenant-isolated (RLS) session + turn persistence."""

    async def create_session(self, session: ConversationSession) -> ConversationSession:
        async with async_session_factory() as db:
            await db.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": session.tenant_id})
            await db.execute(
                text("""
                    INSERT INTO conversation_sessions (session_id, tenant_id, user_id, title, state, pinned, created_at, updated_at)
                    VALUES (:sid, :tid, :uid, :title, :state, :pinned, :created, :updated)
                    ON CONFLICT (session_id) DO NOTHING
                """),
                {
                    "sid": session.session_id, "tid": session.tenant_id, "uid": session.user_id,
                    "title": session.title, "state": session.state.value, "pinned": session.pinned,
                    "created": session.created_at, "updated": session.updated_at,
                },
            )
            await db.commit()
        return session

    async def get_session(self, session_id: str, tenant_id: str) -> Optional[ConversationSession]:
        async with async_session_factory() as db:
            # Real bug caught before this ever shipped: FORCE ROW LEVEL
            # SECURITY denies every row when app.current_tenant_id hasn't
            # been set on this connection yet — so this lookup must set it
            # from the caller's own already-authenticated tenant_id FIRST,
            # not derive it from whatever row RLS lets through (there'd be
            # none). The explicit `AND tenant_id = :tid` below is a second,
            # redundant real check on top of RLS, not a substitute for it.
            await db.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await db.execute(
                text("""
                    SELECT session_id, tenant_id, user_id, title, state, pinned, created_at, updated_at
                    FROM conversation_sessions WHERE session_id = :sid AND tenant_id = :tid
                """),
                {"sid": session_id, "tid": tenant_id},
            )
            row = res.fetchone()
            if not row:
                return None
            turns_res = await db.execute(
                text("""
                    SELECT turn_id, user_query, persona_used, mode_used, assistant_response_json,
                           model_name, latency_ms, cost_usd, created_at
                    FROM conversation_turns WHERE session_id = :sid ORDER BY created_at ASC
                """),
                {"sid": session_id},
            )
            turns = []
            for t in turns_res.fetchall():
                payload = None
                if t.assistant_response_json:
                    try:
                        payload = MultimodalResponsePayload(**t.assistant_response_json)
                    except Exception:
                        payload = None
                turns.append(ConversationTurn(
                    turn_id=t.turn_id, session_id=session_id, user_query=t.user_query,
                    persona_used=t.persona_used or "ENGINEER", mode_used=t.mode_used or "ASK",
                    assistant_response=payload, model_name=t.model_name or "unknown",
                    latency_ms=t.latency_ms or 0.0, cost_usd=t.cost_usd or 0.0,
                    timestamp=t.created_at,
                ))
            return ConversationSession(
                session_id=row.session_id, tenant_id=str(row.tenant_id), user_id=row.user_id,
                title=row.title, state=SessionState(row.state), turns=turns, pinned=row.pinned,
                created_at=row.created_at, updated_at=row.updated_at,
            )

    async def update_session(self, session: ConversationSession) -> ConversationSession:
        async with async_session_factory() as db:
            await db.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": session.tenant_id})
            await db.execute(
                text("""
                    UPDATE conversation_sessions
                    SET title = :title, state = :state, pinned = :pinned, updated_at = :updated
                    WHERE session_id = :sid
                """),
                {"sid": session.session_id, "title": session.title, "state": session.state.value,
                 "pinned": session.pinned, "updated": session.updated_at},
            )
            await db.commit()
        return session

    async def add_turn(self, session_id: str, turn: ConversationTurn, tenant_id: str) -> Optional[ConversationSession]:
        session = await self.get_session(session_id, tenant_id)
        if not session:
            return None
        async with async_session_factory() as db:
            await db.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": session.tenant_id})
            await db.execute(
                text("""
                    INSERT INTO conversation_turns
                        (turn_id, session_id, tenant_id, user_query, persona_used, mode_used,
                         assistant_response_json, model_name, latency_ms, cost_usd, created_at)
                    VALUES (:tid_, :sid, :tid, :query, :persona, :mode, :resp, :model, :lat, :cost, :created)
                    ON CONFLICT (turn_id) DO NOTHING
                """),
                {
                    "tid_": turn.turn_id, "sid": session_id, "tid": session.tenant_id,
                    "query": turn.user_query,
                    "persona": turn.persona_used.value if hasattr(turn.persona_used, "value") else str(turn.persona_used),
                    "mode": turn.mode_used.value if hasattr(turn.mode_used, "value") else str(turn.mode_used),
                    "resp": json.dumps(turn.assistant_response.model_dump()) if turn.assistant_response else None,
                    "model": turn.model_name, "lat": turn.latency_ms, "cost": turn.cost_usd,
                    "created": turn.timestamp,
                },
            )
            await db.execute(
                text("UPDATE conversation_sessions SET updated_at = :updated WHERE session_id = :sid"),
                {"sid": session_id, "updated": turn.timestamp},
            )
            await db.commit()
        session.turns.append(turn)
        session.updated_at = turn.timestamp
        return session

    async def list_sessions(self, tenant_id: str, user_id: str) -> List[ConversationSession]:
        """Lightweight listing (no turns loaded) for a sidebar-style view —
        matches how the in-memory version's only real would-be caller would
        actually want to use it (this method has no live caller yet; kept
        real rather than a stub since Module 6B's sidebar history is a
        natural next caller)."""
        async with async_session_factory() as db:
            await db.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await db.execute(
                text("""
                    SELECT session_id, tenant_id, user_id, title, state, pinned, created_at, updated_at
                    FROM conversation_sessions WHERE tenant_id = :tid AND user_id = :uid
                    ORDER BY updated_at DESC
                """),
                {"tid": tenant_id, "uid": user_id},
            )
            return [
                ConversationSession(
                    session_id=r.session_id, tenant_id=str(r.tenant_id), user_id=r.user_id,
                    title=r.title, state=SessionState(r.state), turns=[], pinned=r.pinned,
                    created_at=r.created_at, updated_at=r.updated_at,
                )
                for r in res.fetchall()
            ]
