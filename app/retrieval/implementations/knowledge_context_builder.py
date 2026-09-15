"""
Knowledge Context Builder Implementation — Module 4
===================================================
Assembles the final KnowledgeContext v1 API response.
"""
from typing import List, Dict, Any
from app.retrieval.interfaces.context_builder import IContextBuilder
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext
from app.retrieval.domain.context import (
    KnowledgeContext, ConfidenceBreakdown, QualityMetrics, RetrievalExplanation
)
from app.retrieval.domain.graph import GraphNode, GraphEdge, GraphPath
from app.retrieval.domain.evidence import EvidenceGroup, Citation, KnowledgeGap

class KnowledgeContextBuilder(IContextBuilder):
    """Builds KnowledgeContext v1 object from candidates and synthesized components."""

    async def build(
        self,
        ctx: RetrievalPipelineContext,
        candidates: List[Candidate],
        graph_data: Dict[str, Any],
        synthesized_data: Dict[str, Any]
    ) -> KnowledgeContext:
        analysis = ctx.analysis or {}
        retrieved_chunks = [
            {"id": c.id, "content": c.content, "score": c.score, "type": c.item_type}
            for c in candidates if "chunk" in c.item_type
        ]

        graph_entities = [
            GraphNode(id=c.id, canonical_name=c.source_metadata.get("canonical_name", c.content), entity_type=c.source_metadata.get("entity_type", "Entity"))
            for c in candidates if c.item_type == "graph_entity"
        ]

        graph_relationships = [
            GraphEdge(
                id=c.id,
                source_id=c.source_metadata.get("source_id", ""),
                source_name=c.source_metadata.get("source_name", ""),
                relationship_type=c.source_metadata.get("relationship_type", "related_to"),
                target_id=c.source_metadata.get("target_id", ""),
                target_name=c.source_metadata.get("target_name", ""),
                weight=c.score
            )
            for c in candidates if c.item_type == "graph_relationship"
        ]

        explanation = RetrievalExplanation(
            selected_strategy=["Dense Search", "BM25 Search", "Multi-Strategy Graph Traversal"],
            excluded_sources=[],
            reason="Standard Retrieval Policy Execution"
        )

        return KnowledgeContext(
            schema_version="1.0",
            query=ctx.query,
            intent=analysis.get("intent", "General"),
            execution_plan=ctx.plan or {},
            retrieved_chunks=retrieved_chunks,
            graph_entities=graph_entities,
            graph_relationships=graph_relationships,
            graph_paths=[],
            derived_facts=synthesized_data.get("derived_facts", []),
            timelines=synthesized_data.get("timelines", []),
            decisions=synthesized_data.get("decisions", []),
            evidence_groups=synthesized_data.get("evidence_groups", []),
            citations=synthesized_data.get("citations", []),
            confidence=synthesized_data.get("confidence") or ConfidenceBreakdown(),
            quality=synthesized_data.get("quality") or QualityMetrics(),
            knowledge_gaps=synthesized_data.get("knowledge_gaps", []),
            retrieval_explanation=explanation,
            execution_trace=ctx.diagnostics,
            metadata={"tenant_id": ctx.tenant_id, "correlation_id": ctx.correlation_id}
        )

knowledge_context_builder = KnowledgeContextBuilder()
