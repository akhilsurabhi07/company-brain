"""Subsystem 20: Conversation Analytics Engine."""

from typing import Dict, Any, List
from pydantic import BaseModel, Field


class AnalyticsEvent(BaseModel):
    tenant_id: str
    session_id: str
    turn_id: str
    latency_ms: float
    cost_usd: float
    tokens: int
    cache_hit: bool
    groundedness_score: float
    citation_coverage: float
    hallucination_detected: bool


class ConversationAnalytics:
    """Tracks latency, cost, tokens, cache hits, groundedness, and hallucination rate."""

    def __init__(self):
        self._events: List[AnalyticsEvent] = []

    def record_event(self, event: AnalyticsEvent) -> None:
        self._events.append(event)

    def get_summary_metrics(self, tenant_id: str) -> Dict[str, Any]:
        tenant_events = [e for e in self._events if e.tenant_id == tenant_id]
        if not tenant_events:
            return {
                "total_turns": 0,
                "avg_latency_ms": 0.0,
                "total_cost_usd": 0.0,
                "cache_hit_rate": 0.0,
                "avg_groundedness": 1.0,
                "hallucination_rate": 0.0,
            }

        total = len(tenant_events)
        avg_lat = sum(e.latency_ms for e in tenant_events) / total
        tot_cost = sum(e.cost_usd for e in tenant_events)
        cache_hits = sum(1 for e in tenant_events if e.cache_hit) / total
        avg_ground = sum(e.groundedness_score for e in tenant_events) / total
        halluc_rate = sum(1 for e in tenant_events if e.hallucination_detected) / total

        return {
            "total_turns": total,
            "avg_latency_ms": round(avg_lat, 2),
            "total_cost_usd": round(tot_cost, 4),
            "cache_hit_rate": round(cache_hits, 4),
            "avg_groundedness": round(avg_ground, 4),
            "hallucination_rate": round(halluc_rate, 4),
        }
