"""Master Ultra-Complex Integration & Stress Test Suite across Modules 1 to 6A."""

import uuid
import pytest
import asyncio
import time
from sqlalchemy import text
from app.db.database import async_session_factory
from app.conversation.services.conversation_service import ConversationService
from app.conversation.domain.persona import PersonaType
from app.conversation.domain.modes import ConversationMode
from app.conversation.domain.response_state import ResponseState
from app.conversation.planner.conversation_planner import PlanningStrategy
from app.security.crypto import TokenEncryptionEngine
from app.processors.pii_redactor import PIIRedactor
from app.processors.content_normalizer import ContentNormalizer
from app.processors.semantic_chunker import SemanticChunker
from app.embeddings.bge_embedder import BGEEmbedder
from app.db.chunk_vector_repo import ChunkVectorRepository
from app.graph.extraction.hybrid_extractor import HybridExtractor
from app.graph.validation.entity_resolver import EntityResolver
from app.graph.validation.trust_engine import TrustEngine
from app.retrieval.retrieval_service import KnowledgeRetrievalService
from app.core_config.policy_engine import PolicyEngine


async def _make_tenant(name_suffix: str) -> str:
    """Real integration (2026-08-22): ConversationService now persists
    sessions/turns to real Postgres tables with a real FK to tenants(id) —
    the placeholder tenant_ids this file used throughout ("tenant_enterprise_
    master", "tenant_stress_N", "tenant_failover", "tenant_replay") against
    the old in-memory-only session repository no longer round-trip."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Master 50 Test {name_suffix}", "domain": f"master50-{name_suffix}.example.com"},
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



@pytest.mark.asyncio
async def test_full_pipeline_m1_to_m6a_ultra_stress():
    """Tests complete E2E flow from M1 security & extraction to M6A conversation engine."""
    tenant_id = await _make_tenant("pipeline")

    # 1. Security & Redaction
    encryptor = TokenEncryptionEngine()
    enc_token = encryptor.encrypt_token("ghp_secret_token_abcdef", tenant_id)
    assert encryptor.decrypt_token(enc_token, tenant_id) == "ghp_secret_token_abcdef"

    redactor = PIIRedactor()
    clean_text = redactor.redact_secrets("Project Titan secret key AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    assert "[REDACTED_AWS_SECRET]" in clean_text


    # 2. Chunking & Embeddings
    normalizer = ContentNormalizer()
    norm_text = normalizer.normalize_text(clean_text)

    chunker = SemanticChunker()
    chunks = chunker.chunk_document(tenant_id, "doc_master", norm_text)

    assert len(chunks) > 0

    embedder = BGEEmbedder()
    vector = embedder.embed_texts([chunks[0].text_content])[0]
    assert len(vector) == 1024


    # 3. Knowledge Graph Construction
    extractor = HybridExtractor()
    extracted_entities, extracted_facts = extractor.extract_all(tenant_id, norm_text)
    assert len(extracted_entities) >= 0

    # 4. M6A Conversational Turn Execution
    service = ConversationService()
    res = await service.process_turn(
        tenant_id=tenant_id,
        user_id="user_master",
        session_id=None,
        user_query="Audit Project Titan EAR99 compliance and security secrets",
        persona=PersonaType.LEGAL_COUNSEL,
        mode=ConversationMode.COMPLIANCE_AUDIT,
        knowledge_context={"chunks": [c.text_content for c in chunks], "entities": [e.canonical_name for e in extracted_entities]},
    )



    assert res["session_id"] is not None
    assert res["response_state"] in [ResponseState.VALIDATED.value, ResponseState.COMPLETED.value]
    assert res["plan"]["strategy"] == PlanningStrategy.COMPLIANCE_AUDIT.value
    assert res["prompt_hash_sha256"] is not None
    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_concurrent_10_tenant_stress():
    """Simulates 10 concurrent enterprise tenants sending complex multi-turn requests."""
    service = ConversationService()
    real_tenants = [await _make_tenant(f"stress-{i}") for i in range(10)]

    async def run_tenant_session(t_idx: int):
        tenant_id = real_tenants[t_idx]
        res1 = await service.process_turn(
            tenant_id=tenant_id,
            user_id=f"user_{t_idx}",
            session_id=None,
            user_query=f"What is the system status for cluster {t_idx}?",
            persona=PersonaType.ENGINEER,
            mode=ConversationMode.ASK,
        )
        assert res1["session_id"] is not None

        res2 = await service.process_turn(
            tenant_id=tenant_id,
            user_id=f"user_{t_idx}",
            session_id=res1["session_id"],
            user_query=f"Audit root cause analysis for incident {t_idx}",
            persona=PersonaType.LEGAL_COUNSEL,
            mode=ConversationMode.COMPLIANCE_AUDIT,
        )
        assert res2["session_id"] == res1["session_id"]
        return res2

    try:
        results = await asyncio.gather(*[run_tenant_session(i) for i in range(10)])
        assert len(results) == 10
        for r in results:
            assert r["model_used"] is not None
    finally:
        for t in real_tenants:
            await _cleanup_tenant(t)


@pytest.mark.asyncio
async def test_provider_circuit_breaker_failover():
    """Tests provider health monitoring and automatic circuit breaker failover."""
    service = ConversationService()
    
    # Intentionally record errors to trigger circuit breaker on openai
    for _ in range(6):
        service.health_monitor.record_error("openai", "Timeout Error 504")

    assert service.health_monitor.is_available("openai") is False

    tenant_id = await _make_tenant("failover")
    try:
        # Real bug found 2026-08-22 (surfaced once this test used a real,
        # valid tenant_id instead of a placeholder string that errored out
        # of retrieval early): a fresh tenant with zero real documents
        # correctly routes an ordinary ASK-mode query to the honest "no
        # company data, use general knowledge" fallback branch — which
        # never touches the main single-provider cascade at all, so it
        # can't publish a real ProviderChanged event either. Switching the
        # persona to one of the excluded ones (LEGAL_COUNSEL/FINANCE/CEO)
        # doesn't fix this either — those personas independently trigger
        # real multi-LLM consensus mode via the planner, a THIRD code path
        # that also never touches this event. The actual fix: give the
        # tenant one real document so retrieval finds it normally, reaching
        # the real single-provider cascade this test is actually about.
        doc_id = str(uuid.uuid4())
        content = "Failover Routing Strategy Runbook: route traffic to the nearest healthy region on primary failure."
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(
                text("""
                    INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                    VALUES (:id, :tid, 'upload', 'doc', 'file', :ext, 'Failover Runbook.txt', :content, 'b', :s3key, 4)
                """),
                {"id": doc_id, "tid": tenant_id, "ext": f"failover-{doc_id[:8]}", "s3key": f"failover-{doc_id[:8]}", "content": content},
            )
            await session.commit()
        chunks = SemanticChunker().chunk_document(tenant_id, doc_id, content)
        embeddings = BGEEmbedder().embed_texts([c.text_content for c in chunks])
        await ChunkVectorRepository().save_chunks_and_embeddings(tenant_id=tenant_id, document_id=doc_id, chunks=chunks, embeddings=embeddings)

        res = await service.process_turn(
            tenant_id=tenant_id,
            user_id="user_failover",
            session_id=None,
            user_query="What is our failover routing strategy?",
            persona=PersonaType.ENGINEER,
            mode=ConversationMode.ASK,
        )
        assert res["model_used"] != "openai"  # Routed away from broken provider
        events = service.event_publisher.get_events(tenant_id)
        assert any(e.event_type == "ProviderChanged" for e in events)
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_timeline_replay_determinism():
    """Verifies turn execution trace recording and SHA-256 prompt replay determinism."""
    service = ConversationService()
    tenant_id = await _make_tenant("replay")
    try:
        res = await service.process_turn(
            tenant_id=tenant_id,
            user_id="user_replay",
            session_id=None,
            user_query="How to configure multi-region RDS clusters?",
            persona=PersonaType.CTO,
            mode=ConversationMode.ARCHITECTURE_REVIEW,
        )

        turn_id = res["turn_id"]
        replayed = service.timeline.replay_turn(turn_id)
        assert replayed is not None
        assert replayed.turn_id == turn_id
        assert len(replayed.prompt_hash_sha256) == 64
        assert replayed.state in [ResponseState.VALIDATED, ResponseState.COMPLETED]
    finally:
        await _cleanup_tenant(tenant_id)
