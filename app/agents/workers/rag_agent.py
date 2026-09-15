import logging
from typing import List, Dict, Any
from app.agents.interfaces.agent_interfaces import BaseSubagent, AgentTaskContext, AgentResult
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever

logger = logging.getLogger("company_brain.agents.rag_agent")

class ResearchRAGAgent(BaseSubagent):
    """
    Research & RAG Subagent Worker.
    Interrogates Module 4 HybridRetriever strictly under PostgreSQL session RLS context (tenant_id).
    Emits machine-checkable trace entries containing SHA-256 query hashes.
    """

    @property
    def agent_name(self) -> str:
        return "ResearchRAGAgent"

    async def execute(self, context: AgentTaskContext) -> AgentResult:
        query_text = context.subtask_query or context.user_query
        tenant_id = context.tenant_id

        try:
            # 1. Execute RLS-Scoped Hybrid Search via Module 4 HybridRetriever
            raw_results = await hybrid_retriever.search(query=query_text, tenant_id=tenant_id, top_k=20)
            chunks_list = raw_results.get("chunks", []) if isinstance(raw_results, dict) else raw_results

            from app.retrieval.implementations.cross_encoder import reranker
            
            # Re-rank the top 20 retrieved chunks down to the best 5
            reranked_chunks = reranker.rerank(query=query_text, chunks=chunks_list, top_n=5)

            # Extract matching chunk objects and citations
            retrieved_chunks = []
            citations = []

            for r in reranked_chunks:
                score_val = r.get("score", 0.0)
                raw_score = r.get("raw_score", score_val)
                # Enforce realistic confidence threshold for hybrid RAG search (0.30 cutoff)
                if score_val < 0.30:
                    continue

                title = r.get("doc_title") or r.get("document_title") or "Untitled Document"
                content_text = r.get("content") or r.get("chunk_content") or ""

                if title not in citations:
                    citations.append(title)
                retrieved_chunks.append({
                    "chunk_id": r.get("id") or r.get("chunk_id"),
                    "document_title": title,
                    "content": content_text,
                    "score": score_val
                })

            # 2. Record Machine-Checkable Agent Trace Entry
            if context.trace_tracker is not None:
                sql_pattern = (
                    "SELECT c.id, c.tenant_id, c.text_content, d.title, (1 - (e.embedding <=> CAST(:vec AS vector))) as score "
                    "FROM document_chunks c JOIN documents d ON c.document_id = d.id "
                    "JOIN embeddings e ON e.chunk_id = c.id WHERE c.tenant_id = :tenant_id "
                    "AND d.resource_category NOT IN ('code_snippet') AND score >= :min_score"
                )
                query_params = {
                    "tenant_id": tenant_id,
                    "query_text": query_text,
                    "top_k": len(retrieved_chunks),
                    "min_score": 0.35,
                    "agent": "ResearchRAGAgent"
                }
                context.trace_tracker.record_step(
                    agent_name=self.agent_name,
                    query_str=sql_pattern,
                    params=query_params,
                    citations=citations,
                    metadata={"result_count": len(retrieved_chunks)}
                )

            summary = f"Retrieved {len(retrieved_chunks)} grounded chunks across {len(citations)} source documents."
            logger.info(f"[{self.agent_name}] Tenant '{tenant_id}' -> {summary}")

            return AgentResult(
                agent_name=self.agent_name,
                success=True,
                retrieved_chunks=retrieved_chunks,
                citations=citations,
                summary_text=summary,
                metadata={"query_text": query_text}
            )

        except Exception as ex:
            logger.error(f"[{self.agent_name} ERROR] Query failed for tenant '{tenant_id}': {ex}")
            return AgentResult(
                agent_name=self.agent_name,
                success=False,
                summary_text=f"Error executing RAG search: {ex}",
                error_message=str(ex)
            )

rag_agent = ResearchRAGAgent()
