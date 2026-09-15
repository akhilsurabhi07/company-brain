"""
Retrieval Orchestrator Engine
==============================
Main entrypoint for knowledge retrieval in Phase 2 & Phase 3.
Orchestrates:
  - VectorRetriever
  - KeywordRetriever
  - PermissionFilter
  - FusionEngine (Reciprocal Rank Fusion RRF)
  - ContextBuilder (RAG Context & Explainability)
"""
import asyncio
from typing import List, Dict, Any, Optional
from app.db.retrievers.vector_retriever import vector_retriever
from app.db.retrievers.context_builder import (
    keyword_retriever,
    permission_filter,
    fusion_engine,
    context_builder,
    RetrievalResult,
)
from app.core_config.tenant_config_service import tenant_config_service

class RetrievalOrchestrator:
    """Master Retrieval Orchestrator Engine."""

    async def retrieve(
        self, tenant_id: str, query_text: str, top_k: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[RetrievalResult]:
        """Unified retrieval entrypoint returning explainable RetrievalResult list."""
        model_name = tenant_config_service.get_tenant_embedding_model(tenant_id)

        # 1 & 2. Execute Vector and Keyword Retrieval concurrently — they're independent
        # (neither depends on the other's result), so running them sequentially only
        # adds real network/DB latency for no reason. This mattered less while
        # KeywordRetriever was a hardcoded stub that returned instantly, but now that
        # it does a real query, serializing the two roughly doubles retrieval latency.
        vec_results, kw_results = await asyncio.gather(
            vector_retriever.retrieve(tenant_id=tenant_id, query_text=query_text, top_k=top_k, model_name=model_name),
            keyword_retriever.retrieve(tenant_id=tenant_id, query_text=query_text, top_k=top_k),
        )

        # 3. Permission Filter (Row-Level Security)
        filtered_vec = permission_filter.filter_by_permissions(vec_results, tenant_id)
        filtered_kw = permission_filter.filter_by_permissions(kw_results, tenant_id)

        # 4. RRF Fusion Re-ranking
        fused_items = fusion_engine.combine_and_rerank(filtered_vec, filtered_kw)

        # 5. Build Explainable RAG Context Results
        results = context_builder.build_results(fused_items[:top_k], model_name=model_name)
        return results

retrieval_orchestrator = RetrievalOrchestrator()
