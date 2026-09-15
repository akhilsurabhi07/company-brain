"""
Master Query Intelligence & Real Data Stress Test Suite — Module 4
===================================================================
Tests multi-domain enterprise intents, runtime intent registration,
conflicting signals, low-confidence fallback, and full data payload context synthesis under RLS.
"""
import pytest
import uuid
from typing import Dict, Any, List
from app.retrieval.domain.retrieval import RetrievalPipelineContext, Candidate
from app.retrieval.domain.intent_registry import intent_registry, EnterpriseIntent
from app.retrieval.domain.query import IntentCandidate, QueryAnalysis, RetrievalPlan
from app.retrieval.domain.context import KnowledgeContext
from app.retrieval.implementations.query_understanding import QueryUnderstandingEngine
from app.retrieval.implementations.knowledge_execution_planner import KnowledgeExecutionPlanner
from app.retrieval.implementations.knowledge_synthesizer import knowledge_synthesizer
from app.retrieval.implementations.evidence_quality_engine import evidence_quality_engine
from app.retrieval.implementations.knowledge_gap_detector import knowledge_gap_detector
from app.retrieval.implementations.knowledge_validator import knowledge_validator

@pytest.mark.asyncio
async def test_complex_multi_domain_intent_disambiguation():
    """Scenario 1: Complex Multi-Domain Query with Financial, Comparison, and Compliance Signals."""
    tenant_id = str(uuid.uuid4())
    ctx = RetrievalPipelineContext(
        correlation_id=f"test_{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        query="Compare Project Titan's Q3 budget allocation vs Project Atlas's Q4 financial spend, and highlight any GDPR compliance risks in the vendor contracts."
    )

    query_intel = QueryUnderstandingEngine()
    planner = KnowledgeExecutionPlanner()

    analysis: QueryAnalysis = await query_intel.analyze(ctx)

    # Verify ranked intents contains FinancialMetric, Comparison, Compliance in HIGH/MEDIUM tiers
    high_med_intents = [c.intent_name for c in analysis.ranked_intents if c.tier in ["HIGH", "MEDIUM"]]
    assert "FinancialMetric" in high_med_intents or "Comparison" in high_med_intents
    assert "Compliance" in high_med_intents or "RiskAnalysis" in high_med_intents
    
    # Verify entity extraction identified both projects
    assert any("Titan" in e for e in analysis.entities)
    assert any("Atlas" in e for e in analysis.entities)

    # Verify multi-signal execution plan synthesis
    plan: RetrievalPlan = await planner.plan(ctx, analysis)
    assert "graph" in plan.strategies
    assert "dense" in plan.strategies
    assert plan.hop_depth >= 3  # Multi-entity comparison requires 3-hop traversal

@pytest.mark.asyncio
async def test_technical_troubleshooting_causal_analysis():
    """Scenario 2: Technical Root-Cause Debugging & System Architecture Query."""
    tenant_id = str(uuid.uuid4())
    ctx = RetrievalPipelineContext(
        correlation_id=f"test_{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        query="Why did the payment service API crash during the ISO audit after microservice v2.4 deployment?"
    )

    query_intel = QueryUnderstandingEngine()
    analysis = await query_intel.analyze(ctx)

    high_med_intents = [c.intent_name for c in analysis.ranked_intents if c.tier in ["HIGH", "MEDIUM"]]
    assert "Troubleshooting" in high_med_intents or "Compliance" in high_med_intents
    assert analysis.reasoning_type in ["Causal", "Lookup", "Dependency"]

@pytest.mark.asyncio
async def test_runtime_dynamic_intent_registration():
    """Scenario 3: Dynamically register a new Mergers & Acquisitions intent at runtime."""
    # Dynamically register custom intent
    custom_intent = EnterpriseIntent(
        name="MAndAAssessment",
        category="Governance",
        description="Mergers, acquisitions, target valuations, and corporate buyouts.",
        keywords=["acquisition", "buyout", "m&a", "takeover", "target valuation"],
        default_reasoning="Aggregation",
        default_output_constraint="dependency_analysis"
    )
    intent_registry.register_intent(custom_intent)

    # Issue query relying on the newly registered intent
    tenant_id = str(uuid.uuid4())
    ctx = RetrievalPipelineContext(
        correlation_id=f"test_{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        query="What are the legal regulatory risks and target valuation in the Acquisition of Acme Corp?"
    )

    query_intel = QueryUnderstandingEngine()
    analysis = await query_intel.analyze(ctx)

    # Assert newly registered intent was scored as top HIGH candidate
    assert analysis.primary_intent == "MAndAAssessment" or "MAndAAssessment" in [c.intent_name for c in analysis.ranked_intents if c.tier == "HIGH"]
    assert any(c.intent_name == "MAndAAssessment" for c in analysis.ranked_intents)

@pytest.mark.asyncio
async def test_conflicting_signals_and_low_confidence_fallback():
    """Scenario 4: Nonsense or generic query triggers low confidence broad retrieval fallback."""
    tenant_id = str(uuid.uuid4())
    ctx = RetrievalPipelineContext(
        correlation_id=f"test_{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        query="foo bar baz generic text 12345"
    )

    query_intel = QueryUnderstandingEngine()
    planner = KnowledgeExecutionPlanner()

    analysis = await query_intel.analyze(ctx)
    plan = await planner.plan(ctx, analysis)

    # Verify fallback strategy contains all 3 retrievers and higher resource budget
    assert "dense" in plan.strategies
    assert "bm25" in plan.strategies
    assert "graph" in plan.strategies
    assert plan.resource_budget_ms >= 500

@pytest.mark.asyncio
async def test_full_data_payload_synthesis_and_quality_certification():
    """Scenario 5: Real realistic data payload passed through synthesis, gap detection, quality scoring, and validation."""
    candidates = [
        Candidate(
            id="c1",
            item_type="dense_chunk",
            content="Project Phoenix milestone delay announced in Slack due to Legal review backlog.",
            score=0.92,
            source_metadata={"author": "Alice", "source_system": "Slack", "period": "2026-07-20"}
        ),
        Candidate(
            id="c2",
            item_type="graph_fact",
            content="Fact: Project Phoenix blocked by Legal Department Approval.",
            score=0.96,
            source_metadata={"source_system": "Jira", "period": "2026-07-21"}
        ),
        Candidate(
            id="c3",
            item_type="graph_decision",
            content="Decision: Legal review turnaround target set for August 1 2026.",
            score=0.90,
            source_metadata={"source_system": "Confluence", "decided_at": "2026-07-22"}
        )
    ]

    # Validate candidates
    ctx = RetrievalPipelineContext(correlation_id="t1", tenant_id="t1", query="Why is Project Phoenix delayed?")
    valid_candidates = knowledge_validator.validate(ctx, candidates)
    assert len(valid_candidates) == 3

    # Synthesize timelines and facts
    synth = knowledge_synthesizer.synthesize(valid_candidates)
    assert len(synth["timelines"]) >= 2
    assert len(synth["derived_facts"]) >= 1

    # Detect knowledge gaps
    gaps = knowledge_gap_detector.detect_gaps(valid_candidates)
    assert isinstance(gaps, list)

    # Evaluate composite quality & citations
    conf, qual, citations = evidence_quality_engine.evaluate_quality_and_citations(valid_candidates)
    assert conf.overall > 0.85
    assert len(citations) == 3
