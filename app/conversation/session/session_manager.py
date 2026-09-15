"""Subsystem 1: Conversation Session Manager."""

from typing import Optional, List
from app.conversation.domain.context import ConversationSession, ConversationTurn
from app.conversation.domain.states import SessionState, SessionStateMachine
from app.conversation.interfaces.session_interface import BaseSessionRepository


class SessionManager:
    """Manages session creation, state transitions, pinning, and expiration."""

    def __init__(self, repository: BaseSessionRepository):
        self.repository = repository

    async def create_session(self, tenant_id: str, user_id: str, title: str = "New Conversation") -> ConversationSession:
        session = ConversationSession(tenant_id=tenant_id, user_id=user_id, title=title, state=SessionState.CREATED)
        session.state = SessionStateMachine.transition(session.state, SessionState.ACTIVE)
        return await self.repository.create_session(session)

    async def get_session(self, session_id: str, tenant_id: str) -> Optional[ConversationSession]:
        return await self.repository.get_session(session_id, tenant_id)

    async def archive_session(self, session_id: str, tenant_id: str) -> Optional[ConversationSession]:
        session = await self.repository.get_session(session_id, tenant_id)
        if not session:
            return None
        session.state = SessionStateMachine.transition(session.state, SessionState.ARCHIVED)
        return await self.repository.update_session(session)

    async def expire_session(self, session_id: str, tenant_id: str) -> Optional[ConversationSession]:
        session = await self.repository.get_session(session_id, tenant_id)
        if not session:
            return None
        session.state = SessionStateMachine.transition(session.state, SessionState.EXPIRED)
        return await self.repository.update_session(session)
