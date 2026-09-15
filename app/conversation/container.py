"""Dependency Injection Container for Module 6A."""

from app.conversation.services.conversation_service import ConversationService


class ConversationContainer:
    """Singleton Container providing dependency injection for Module 6A services."""

    _SERVICE_INSTANCE: ConversationService = None

    @classmethod
    def get_conversation_service(cls) -> ConversationService:
        if cls._SERVICE_INSTANCE is None:
            cls._SERVICE_INSTANCE = ConversationService()
        return cls._SERVICE_INSTANCE
