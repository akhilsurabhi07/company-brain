"""Test Suite 7: Module 6A Ultra-Complex Multi-Tenant Stress Test."""

import pytest
import asyncio
from app.conversation.services.conversation_service import ConversationService
from app.conversation.domain.persona import PersonaType
from app.conversation.domain.modes import ConversationMode


@pytest.mark.asyncio
async def test_module6a_ultra_complex_stress():
    service = ConversationService()

    # 1. Execute turn with Engineer persona
    res1 = await service.process_turn(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="user_1",
        session_id=None,
        user_query="What is the deployment status of Project Phoenix?",
        persona=PersonaType.ENGINEER,
        mode=ConversationMode.ASK,
    )
    assert res1["session_id"] is not None
    assert res1["latency_ms"] >= 0.0


    # 2. Execute turn with Consensus for Legal persona
    res2 = await service.process_turn(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="user_1",
        session_id=res1["session_id"],
        user_query="Audit EAR99 export control compliance",
        persona=PersonaType.LEGAL_COUNSEL,
        mode=ConversationMode.COMPLIANCE_AUDIT,
        use_consensus=True,
    )
    assert res2["model_used"] == "multi-llm-consensus"
    assert res2["review"]["is_approved"] is True

    # 3. Test Cache Hit on identical query
    res3 = await service.process_turn(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="user_1",
        session_id=res1["session_id"],
        user_query="What is the deployment status of Project Phoenix?",
        persona=PersonaType.ENGINEER,
        mode=ConversationMode.ASK,
    )
    assert res3["cache_hit"] is True

    # 4. Verify Explanation Engine
    # Stale test fixed 2026-08-21: ConversationService.get_explanation() never
    # existed as a standalone method in the current codebase (grep confirms zero
    # definitions anywhere in app/) — explanation building has always been inline
    # in process_turn's own returned "explanation" dict on the real, grounded RAG
    # path (see conversation_service.py's `result["explanation"] =
    # explanation_res.model_dump()`). This test predates that shape and was
    # calling a method that doesn't exist; asserting on the real inline field
    # that res1 (a real grounded turn) already returned instead.
    assert res1["explanation"]["grounding_status"] == "VERIFIED_GROUNDED"
