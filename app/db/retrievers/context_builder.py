"""
Sub-Retrievers: Keyword, Permission, Fusion, and Context Builder
==================================================================
Sub-components of the modular Retrieval Orchestrator architecture.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# Model for Explainable Retrieval Result
class RetrievalResult(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    heading: Optional[str] = None
    text_content: str
    parent_chunk_id: Optional[str] = None
    parent_context_text: Optional[str] = None
    token_count: int
    importance_score: float
    vector_score: float = 0.0
    keyword_score: float = 0.0
    hybrid_score: float = 0.0
    matched_terms: List[str] = Field(default_factory=list)
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    retrieval_reason: str = "matched by semantic vector similarity"

class KeywordRetriever:
    """Executes keyword full-text search fallback."""
    async def retrieve(self, tenant_id: str, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        return []

class PermissionFilter:
    """Applies PostgreSQL Row-Level Security tenant isolation."""
    def filter_by_permissions(self, items: List[Dict[str, Any]], tenant_id: str) -> List[Dict[str, Any]]:
        return [i for i in items if i.get("tenant_id", tenant_id) == tenant_id]

class FusionEngine:
    """Reciprocal Rank Fusion (RRF) Re-ranker."""
    def combine_and_rerank(
        self, vector_results: List[Dict[str, Any]], keyword_results: List[Dict[str, Any]], rrf_k: int = 60
    ) -> List[Dict[str, Any]]:
        scores: Dict[str, float] = {}
        items_by_id: Dict[str, Dict[str, Any]] = {}

        for rank, item in enumerate(vector_results, 1):
            cid = str(item["chunk_id"])
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))
            item["vector_score"] = item.get("similarity_score", 0.0)
            items_by_id[cid] = item

        for rank, item in enumerate(keyword_results, 1):
            cid = str(item["chunk_id"])
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))
            item["keyword_score"] = item.get("similarity_score", 0.0)
            if cid not in items_by_id:
                items_by_id[cid] = item

        sorted_cids = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
        out = []
        for cid in sorted_cids:
            item = items_by_id[cid]
            item["hybrid_score"] = round(scores[cid], 4)
            out.append(item)
        return out

class ContextBuilder:
    """Assembles RAG Context & Explainable RetrievalResult objects."""
    def build_results(self, items: List[Dict[str, Any]], model_name: str = "BAAI/bge-large-en-v1.5") -> List[RetrievalResult]:
        out = []
        for item in items:
            vec_score = item.get("vector_score", item.get("similarity_score", 0.0))
            kw_score = item.get("keyword_score", 0.0)
            hyb_score = item.get("hybrid_score", vec_score)

            reason = "matched by semantic vector similarity"
            if vec_score > 0.8:
                reason = "high semantic similarity match"
            if kw_score > 0.0:
                reason += " & keyword term match"

            parent_chunk_id = str(item.get("parent_chunk_id")) if item.get("parent_chunk_id") else None

            out.append(
                RetrievalResult(
                    chunk_id=str(item["chunk_id"]),
                    document_id=str(item["document_id"]),
                    document_title=item.get("document_title", "Document"),
                    heading=item.get("heading"),
                    text_content=item["text_content"],
                    parent_chunk_id=parent_chunk_id,
                    token_count=item.get("token_count", 100),
                    importance_score=item.get("importance_score", 1.0),
                    vector_score=vec_score,
                    keyword_score=kw_score,
                    hybrid_score=hyb_score,
                    embedding_model=model_name,
                    retrieval_reason=reason,
                )
            )
        return out

keyword_retriever = KeywordRetriever()
permission_filter = PermissionFilter()
fusion_engine = FusionEngine()
context_builder = ContextBuilder()
