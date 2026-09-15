"""Event Publisher Subsystem for Module 6A."""

import time
from typing import Dict, Any, List
from pydantic import BaseModel, Field


class ConversationEvent(BaseModel):
    event_type: str
    tenant_id: str
    session_id: str
    timestamp: float = Field(default_factory=time.time)
    payload: Dict[str, Any] = Field(default_factory=dict)


class EventPublisher:
    """Emits structured conversation lifecycle events for downstream observability and Module 9 consumption."""

    def __init__(self):
        self._published_events: List[ConversationEvent] = []

    def publish(self, event_type: str, tenant_id: str, session_id: str, payload: Dict[str, Any]):
        event = ConversationEvent(
            event_type=event_type,
            tenant_id=tenant_id,
            session_id=session_id,
            payload=payload,
        )
        self._published_events.append(event)

    def get_events(self, tenant_id: str = None) -> List[ConversationEvent]:
        if tenant_id:
            return [e for e in self._published_events if e.tenant_id == tenant_id]
        return self._published_events
