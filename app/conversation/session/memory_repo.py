"""In-Memory Session Repository Implementation."""

from typing import Dict, List, Optional
from app.conversation.domain.context import ConversationSession, ConversationTurn
from app.conversation.interfaces.session_interface import BaseSessionRepository


class InMemorySessionRepository(BaseSessionRepository):
    """Thread-safe in-memory session repository."""

    def __init__(self):
        self._store: Dict[str, ConversationSession] = {}

    async def create_session(self, session: ConversationSession) -> ConversationSession:
        self._store[session.session_id] = session
        return session

    async def get_session(self, session_id: str, tenant_id: str) -> Optional[ConversationSession]:
        session = self._store.get(session_id)
        # A dict lookup has no RLS to rely on — check tenant_id explicitly so
        # this stays a safe drop-in for PostgresSessionRepository, which needs
        # tenant_id for the same reason.
        if session and session.tenant_id != tenant_id:
            return None
        return session

    async def update_session(self, session: ConversationSession) -> ConversationSession:
        self._store[session.session_id] = session
        return session

    async def add_turn(self, session_id: str, turn: ConversationTurn, tenant_id: str) -> ConversationSession:
        session = self._store.get(session_id)
        if session and session.tenant_id != tenant_id:
            return None
        if session:
            session.turns.append(turn)
            session.updated_at = turn.timestamp
            self._store[session_id] = session
        return session

    async def list_sessions(self, tenant_id: str, user_id: str) -> List[ConversationSession]:
        return [s for s in self._store.values() if s.tenant_id == tenant_id and s.user_id == user_id]
