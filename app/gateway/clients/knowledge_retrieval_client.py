"""
Knowledge Retrieval Client Adapter — Module 5 EKAP
===================================================
Decoupled client adapter wrapping Module 4's KnowledgeRetrievalService.
Consumes KnowledgeContext v1 without modifying Module 4.
"""
from typing import Optional
from app.retrieval.domain.context import KnowledgeContext
from app.retrieval.retrieval_service import knowledge_retrieval_service

class KnowledgeRetrievalClient:
    """Client wrapper consuming Module 4 GraphRAG engine output."""

    async def retrieve_context(
        self,
        tenant_id: str,
        query: str,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> KnowledgeContext:
        """Executes retrieval against Module 4 under RLS isolation."""
        return await knowledge_retrieval_service.execute_retrieval(
            tenant_id=tenant_id,
            query=query,
            user_id=user_id,
            correlation_id=correlation_id
        )

knowledge_retrieval_client = KnowledgeRetrievalClient()
