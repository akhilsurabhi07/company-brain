"""
Sub-Retriever 1: Vector Retriever
=================================
Executes pgvector HNSW Cosine Similarity search.
"""
import asyncio
from typing import List, Dict, Any
from app.db.chunk_vector_repo import chunk_vector_repo
from app.embeddings.bge_embedder import bge_embedder

class VectorRetriever:
    """Executes dense vector similarity search."""

    async def retrieve(
        self, tenant_id: str, query_text: str, top_k: int = 5, model_name: str = "BAAI/bge-large-en-v1.5"
    ) -> List[Dict[str, Any]]:
        # 1. Embed query text using BGE (offloaded so CPU-bound inference doesn't block the event loop)
        query_vectors = await asyncio.to_thread(bge_embedder.embed_texts, [query_text])
        if not query_vectors:
            return []

        # 2. Execute pgvector search
        return await chunk_vector_repo.execute_vector_similarity_search(
            tenant_id=tenant_id, query_vector=query_vectors[0], top_k=top_k, model_name=model_name
        )

vector_retriever = VectorRetriever()
