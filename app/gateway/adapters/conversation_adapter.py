"""
ConversationService -> KnowledgeContext v1 Adapter — Module 5 EKAP
====================================================================
Real integration (2026-08-22): Module 5's search pipeline used to call the
separate, less-mature Module 4 `knowledge_retrieval_service` pipeline
(app/gateway/clients/knowledge_retrieval_client.py) directly, then run its
own duplicate/inferior RBAC filtering on top
(app/gateway/authorization/policy_engine.py::filter_context_for_user).

That duplicated — and regressed — real, already-fixed behavior that lives
in `ConversationService.process_turn()`: sentence-level RBAC/ABAC redaction
of restricted content (salary/payroll/compensation/bonus terms), multi-hop
graph traversal, decisions/facts surfacing, grounding, and citation
validation. Rather than reimplement any of that a second time, the Gateway
now calls straight into `ConversationService.process_turn()` — the same
live, fully-tested pipeline backing `/api/v6a/chat/turn` — and this adapter
reshapes its plain result dict into a `KnowledgeContext` v1 object purely so
Module 5's existing (real, working) markdown/agent/dashboard/mobile format
transformers keep working unchanged.
"""
from typing import Any, Dict

from app.retrieval.domain.context import ConfidenceBreakdown, KnowledgeContext
from app.retrieval.domain.evidence import Citation


def process_turn_result_to_knowledge_context(result: Dict[str, Any], query: str) -> KnowledgeContext:
    # NOTE: result["response"]["citations"] (MultimodalResponsePayload.citations)
    # is LLM-provider attribution metadata (e.g. {"source": "Groq (...)",
    # "trust_score": 0.97}) — which model generated the answer — not document
    # citations. The real evidence/document titles used as grounding for this
    # turn live in explanation.evidence_used (doc_title/source_app/rerank_score),
    # built by ExplanationEngine from the actual retrieved+redacted chunks list.
    explanation = result.get("explanation") or {}
    evidence_used = explanation.get("evidence_used") or []

    retrieved_chunks = [
        {"content": item.get("doc_title", "Untitled"), "score": item.get("rerank_score") or 0.8}
        for item in evidence_used
        if isinstance(item, dict)
    ]
    derived_facts = [
        {"content": item.get("doc_title", "Untitled")}
        for item in evidence_used
        if isinstance(item, dict) and item.get("source_app") in ("graph", "decision")
    ]

    citations = [
        Citation(
            citation_id=f"c{i + 1}",
            title=str(item.get("doc_title", "Untitled")),
            source_app=str(item.get("source_app", "document")),
            snippet="",
        )
        for i, item in enumerate(evidence_used)
        if isinstance(item, dict)
    ]

    confidence_pct = result.get("confidence_score", 0)
    try:
        overall_confidence = float(confidence_pct) / 100.0
    except (TypeError, ValueError):
        overall_confidence = 0.0

    grounding = result.get("grounding") or {}
    citation_res = result.get("citation") or {}

    return KnowledgeContext(
        query=query,
        intent="conversational_qa",
        retrieved_chunks=retrieved_chunks,
        derived_facts=derived_facts,
        citations=citations,
        confidence=ConfidenceBreakdown(
            overall=overall_confidence,
            retrieval=overall_confidence,
            graph=overall_confidence,
            citation=float(citation_res.get("citation_coverage", 1.0)) if citation_res else 1.0,
            reasoning=overall_confidence,
        ),
        metadata={
            "response_text": result.get("response_text", ""),
            "turn_id": result.get("turn_id", ""),
            "session_id": result.get("session_id", ""),
            "model_used": result.get("model_used", ""),
            "grounding_status": explanation.get("grounding_status", ""),
            "is_grounded": grounding.get("is_grounded"),
            "reasoning_summary": explanation.get("reasoning_summary", ""),
        },
    )
