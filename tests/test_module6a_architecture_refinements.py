"""Test Suite for Module 6A Architectural Refinements."""

import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.planner.conversation_planner import ConversationPlanner, PlanningStrategy
from app.conversation.runtime.provider_health import ProviderHealthMonitor
from app.conversation.events.event_publisher import EventPublisher
from app.conversation.domain.response_state import ResponseState
from app.conversation.domain.timeline import ConversationTimeline
from app.conversation.services.conversation_service import ConversationService
from app.conversation.domain.persona import PersonaType
from app.conversation.domain.modes import ConversationMode


async def _make_tenant(name_suffix: str) -> str:
    """Real integration (2026-08-22): ConversationService now persists
    sessions/turns to real Postgres tables with a real FK to tenants(id) —
    the placeholder "tenant_alpha" this test used against the old
    in-memory-only session repository no longer round-trips."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Refinements Test {name_suffix}", "domain": f"refine-{name_suffix}.example.com"},
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


def test_conversation_planner():
    planner = ConversationPlanner()
    plan1 = planner.plan_conversation("Audit EAR99 compliance", "ASK", "ENGINEER")
    assert plan1.strategy == PlanningStrategy.COMPLIANCE_AUDIT
    assert plan1.requires_consensus is True

    plan2 = planner.plan_conversation("What is the root cause of incident 101?", "ASK", "ENGINEER")
    assert plan2.strategy == PlanningStrategy.ROOT_CAUSE_ANALYSIS


def test_provider_health_monitor():
    health = ProviderHealthMonitor()
    assert health.is_available("openai") is True
    assert "openai" in health.get_healthy_providers()

    # Simulate errors
    for _ in range(6):
        health.record_error("openai", "Connection timeout")

    assert health.is_available("openai") is False
    assert "openai" not in health.get_healthy_providers()


def test_event_publisher():
    publisher = EventPublisher()
    publisher.publish("ConversationStarted", "tenant_a", "session_1", {"query": "test"})
    events = publisher.get_events("tenant_a")
    assert len(events) == 1
    assert events[0].event_type == "ConversationStarted"


def test_timeline_and_replay():
    timeline = ConversationTimeline()
    trace = timeline.record_turn(
        turn_id="turn_101",
        session_id="session_1",
        user_query="How to deploy?",
        compiled_prompt="System: Deploy guide",
        provider_used="openai",
        state=ResponseState.VALIDATED,
        latency_ms=120.0,
        token_count=100,
        response_text="Run deployment script.",
    )
    assert trace.prompt_hash_sha256 is not None
    assert len(trace.prompt_hash_sha256) == 64

    replayed = timeline.replay_turn("turn_101")
    assert replayed is not None
    assert replayed.user_query == "How to deploy?"


@pytest.mark.asyncio
async def test_conversation_service_with_refinements():
    tenant_id = await _make_tenant("svc")
    try:
        service = ConversationService()
        res = await service.process_turn(
            tenant_id=tenant_id,
            user_id="user_1",
            session_id=None,
            user_query="Audit EAR99 export control compliance",
            persona=PersonaType.LEGAL_COUNSEL,
            mode=ConversationMode.COMPLIANCE_AUDIT,
        )
        assert res["response_state"] in [ResponseState.VALIDATED.value, ResponseState.COMPLETED.value]
        assert res["prompt_hash_sha256"] is not None
        assert "plan" in res
        assert res["plan"]["strategy"] == PlanningStrategy.COMPLIANCE_AUDIT.value
        events = service.event_publisher.get_events(tenant_id)
        assert len(events) >= 2
    finally:
        await _cleanup_tenant(tenant_id)
