"""Abstract Session Repository Interface."""

from abc import ABC, abstractmethod
from typing import List, Optional
from app.conversation.domain.context import ConversationSession, ConversationTurn


class BaseSessionRepository(ABC):
    """Abstract contract for conversation session persistence.

    get_session/add_turn take an explicit tenant_id (added 2026-08-22, real
    integration with PostgresSessionRepository): a real RLS-backed repository
    can't look up a session by session_id alone without already knowing which
    tenant's RLS context to set first — the caller (ConversationService)
    always has the real, authenticated tenant_id in hand at these call sites
    anyway, so passing it through costs nothing and closes what would
    otherwise be a real cross-tenant lookup gap."""

    @abstractmethod
    async def create_session(self, session: ConversationSession) -> ConversationSession:
        pass

    @abstractmethod
    async def get_session(self, session_id: str, tenant_id: str) -> Optional[ConversationSession]:
        pass

    @abstractmethod
    async def update_session(self, session: ConversationSession) -> ConversationSession:
        pass

    @abstractmethod
    async def add_turn(self, session_id: str, turn: ConversationTurn, tenant_id: str) -> ConversationSession:
        pass

    @abstractmethod
    async def list_sessions(self, tenant_id: str, user_id: str) -> List[ConversationSession]:
        pass
