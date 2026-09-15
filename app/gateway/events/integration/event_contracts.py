"""
Integration Event Bus Contracts — Module 5 EKAP
================================================
Events published after successful client response delivery.
"""
from typing import Dict, Any
from pydantic import BaseModel, Field

class SearchCompletedEvent(BaseModel):
    event_name: str = "SearchCompleted"
    tenant_id: str
    user_id: str
    query: str
    intent: str
    result_count: int
    cost_units: int
    latency_ms: float
    timestamp: str

class AuditRecordedEvent(BaseModel):
    event_name: str = "AuditRecorded"
    tenant_id: str
    user_id: str
    role: str
    endpoint: str
    timestamp: str

class EventBus:
    """Publish-subscribe event bus for Gateway Integration Events."""

    def __init__(self):
        self._published_events = []

    def publish(self, event: BaseModel) -> None:
        self._published_events.append(event)

event_bus = EventBus()
