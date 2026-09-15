"""
Knowledge Retrieval Service — Module 4 Main Entry Point
======================================================
Internal service facade orchestrating the complete 11-stage retrieval pipeline under RLS.
"""
import asyncio
import time
import uuid
from typing import List, Dict, Any, Optional
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext
from app.retrieval.domain.context import KnowledgeContext
from app.retrieval.container import container
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever
from app.retrieval.fusion.strategies.rrf import apply_rrf
from app.retrieval.fusion.strategies.graph_priority import apply_graph_priority_fusion
from app.retrieval.implementations.evidence_orchestrator import evidence_orchestrator
from app.retrieval.implementations.knowledge_synthesizer import knowledge_synthesizer
from app.retrieval.implementations.knowledge_validator import knowledge_validator
from app.retrieval.implementations.knowledge_gap_detector import knowledge_gap_detector
from app.retrieval.implementations.evidence_quality_engine import evidence_quality_engine
from app.retrieval.infrastructure.cache.semantic_retrieval_cache import semantic_cache
from app.retrieval.infrastructure.telemetry.retrieval_tracer import retrieval_tracer

class KnowledgeRetrievalService:
    """Orchestrates the Knowledge Retrieval Engine pipeline."""

    def __init__(self):
        # Per tenant+query in-flight locks. Without these, N concurrent requests for the
        # same (uncached) query all race past the cache check and each run the full
        # pipeline redundantly (a classic cache-stampede) instead of N-1 of them simply
        # waiting on the first request's result.
        self._inflight_locks: Dict[str, asyncio.Lock] = {}

    def _lock_for(self, tenant_id: str, query: str) -> asyncio.Lock:
        key = f"{tenant_id}:{query.strip().lower()}"
        lock = self._inflight_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._inflight_locks[key] = lock
        return lock

    async def execute_retrieval(
        self,
        tenant_id: str,
        query: str,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> KnowledgeContext:
        # 1. Semantic Cache Check
        t0 = time.time()
        cached = await semantic_cache.get(tenant_id, query)
        cache_check_ms = (time.time() - t0) * 1000
        if cached:
            cached["execution_trace"]["cache_hit"] = True
            return KnowledgeContext(**cached)

        # Coalesce concurrent identical requests: only the first one runs the pipeline,
        # the rest wait here then re-check cache before falling through to their own run.
        async with self._lock_for(tenant_id, query):
            cached = await semantic_cache.get(tenant_id, query)
            if cached:
                cached["execution_trace"]["cache_hit"] = True
                return KnowledgeContext(**cached)

            return await self._run_pipeline(tenant_id, query, user_id, correlation_id, cache_check_ms)

    async def _run_pipeline(
        self,
        tenant_id: str,
        query: str,
        user_id: Optional[str],
        correlation_id: Optional[str],
        cache_check_ms: float,
    ) -> KnowledgeContext:
        corr_id = correlation_id or f"req_{uuid.uuid4().hex[:8]}"
        trace = retrieval_tracer.start_trace(corr_id)
        retrieval_tracer.record_step(trace, "semantic_cache_check", cache_check_ms)

        # Build Pipeline Context
        ctx = RetrievalPipelineContext(
            correlation_id=corr_id,
            tenant_id=tenant_id,
            user_id=user_id,
            query=query
        )

        # 2. Query Intelligence
        t0 = time.time()
        analysis = await container.query_intelligence.analyze(ctx)
        ctx.analysis = analysis.model_dump()
        retrieval_tracer.record_step(trace, "query_intelligence", (time.time() - t0) * 1000)

        # 3. Execution Planner
        t0 = time.time()
        plan = await container.execution_planner.plan(ctx, analysis)
        ctx.plan = plan.model_dump()
        retrieval_tracer.record_step(trace, "execution_planner", (time.time() - t0) * 1000)

        # 4. Policy Engine
        t0 = time.time()
        policy_valid = await container.policy_engine.validate_policy(ctx)
        retrieval_tracer.record_step(trace, "policy_engine", (time.time() - t0) * 1000)
        if not policy_valid:
            raise ValueError("Retrieval Policy Violation: Invalid tenant or correlation context.")

        # 5. Parallel Retrieval (Dense + BM25 + Graph)
        t0 = time.time()
        dense_bm25_candidates = []
        try:
            # Query existing hybrid retriever
            h_res = await hybrid_retriever.search(tenant_id, query, top_k=plan.resource_budget_ms)
            for idx, item in enumerate(h_res.get("chunks", [])):
                dense_bm25_candidates.append(Candidate(
                    id=item.get("id", f"c_{idx}"),
                    item_type="dense_chunk",
                    content=item.get("content", ""),
                    score=item.get("score", 0.8),
                    source_metadata=item
                ))
        except Exception:
            pass  # Degrade gracefully if hybrid vector search fails

        graph_candidates = []
        if "graph" in plan.strategies:
            try:
                graph_candidates = await container.graph_retriever.retrieve(ctx, plan)
            except Exception:
                pass  # Degrade gracefully if graph database fails
        retrieval_tracer.record_step(trace, "parallel_retrieval", (time.time() - t0) * 1000)

        # 6. Hybrid Fusion
        t0 = time.time()
        fused_candidates = apply_graph_priority_fusion([dense_bm25_candidates, [], graph_candidates])
        retrieval_tracer.record_step(trace, "hybrid_fusion", (time.time() - t0) * 1000)

        # 7. Evidence Orchestration & Reranking
        t0 = time.time()
        orchestrated_groups = evidence_orchestrator.orchestrate(fused_candidates)
        reranked_candidates = await container.reranker.rerank(ctx, fused_candidates, top_k=10)
        retrieval_tracer.record_step(trace, "reranking", (time.time() - t0) * 1000)

        # 8. Knowledge Synthesizer & Validator
        t0 = time.time()
        synth_res = knowledge_synthesizer.synthesize(reranked_candidates)
        valid_candidates = knowledge_validator.validate(ctx, reranked_candidates)
        retrieval_tracer.record_step(trace, "synthesis_and_validation", (time.time() - t0) * 1000)

        # 9. Knowledge Gap Detector & Evidence Quality Engine
        t0 = time.time()
        gaps = knowledge_gap_detector.detect_gaps(valid_candidates)
        conf, qual, citations = evidence_quality_engine.evaluate_quality_and_citations(valid_candidates)
        retrieval_tracer.record_step(trace, "gaps_and_quality", (time.time() - t0) * 1000)

        # Package Synthesized Data
        synth_data = {
            "derived_facts": synth_res.get("derived_facts", []),
            "timelines": synth_res.get("timelines", []),
            "decisions": [],
            "evidence_groups": orchestrated_groups,
            "citations": citations,
            "confidence": conf,
            "quality": qual,
            "knowledge_gaps": gaps
        }

        # 10. Knowledge Context Builder
        t0 = time.time()
        ctx.diagnostics = retrieval_tracer.finalize_trace(trace)
        k_context = await container.context_builder.build(ctx, valid_candidates, {}, synth_data)
        retrieval_tracer.record_step(trace, "context_building", (time.time() - t0) * 1000)

        # Cache result
        await semantic_cache.set(tenant_id, query, k_context.model_dump())
        return k_context

knowledge_retrieval_service = KnowledgeRetrievalService()
