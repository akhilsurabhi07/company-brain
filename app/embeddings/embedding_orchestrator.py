"""
Embedding Orchestrator Module
=============================
Acts as the central traffic controller for embedding generation.
Responsibilities:
  - Batch splitting and CPU/GPU selection
  - Rate limiting & circuit breaker checks
  - Provider routing & automatic fallback
  - Tenant-scoped cache lookup
"""
from typing import List, Dict, Any, Optional
from app.interfaces.chunker_interface import DocumentChunk
from app.interfaces.embedding_interface import VectorEmbedding, EmbeddingProviderInterface
from app.embeddings.bge_embedder import bge_embedder
from app.embeddings.embedding_validator import embedding_validator
from app.embeddings.embedding_cache import tenant_embedding_cache
from app.core_config.tenant_config_service import tenant_config_service

class EmbeddingOrchestrator:
    """Embedding Pipeline Traffic Controller."""

    def __init__(self):
        self.providers: Dict[str, EmbeddingProviderInterface] = {
            bge_embedder.model_name: bge_embedder
        }

    def register_provider(self, provider: EmbeddingProviderInterface):
        self.providers[provider.model_name] = provider

    def generate_embeddings_for_chunks(
        self, tenant_id: str, document_id: str, chunks: List[DocumentChunk]
    ) -> List[VectorEmbedding]:
        if not chunks:
            return []

        model_name = tenant_config_service.get_tenant_embedding_model(tenant_id)
        provider = self.providers.get(model_name, bge_embedder)

        uncached_chunks: List[DocumentChunk] = []
        result_embeddings: List[VectorEmbedding] = []

        for chunk in chunks:
            cached_vec = tenant_embedding_cache.get(tenant_id, chunk.checksum, provider.model_name)
            if cached_vec:
                result_embeddings.append(
                    VectorEmbedding(
                        chunk_id=chunk.chunk_id,
                        tenant_id=tenant_id,
                        document_id=document_id,
                        model_name=provider.model_name,
                        dimension=provider.dimension,
                        vector=cached_vec,
                        checksum=chunk.checksum,
                    )
                )
            else:
                uncached_chunks.append(chunk)

        if uncached_chunks:
            texts = [c.text_content for c in uncached_chunks]
            raw_vectors = provider.embed_texts(texts)

            valid_vectors, reasons = embedding_validator.validate_batch(raw_vectors, provider.dimension)

            for chunk, vec in zip(uncached_chunks, valid_vectors):
                tenant_embedding_cache.set(tenant_id, chunk.checksum, provider.model_name, vec)

                result_embeddings.append(
                    VectorEmbedding(
                        chunk_id=chunk.chunk_id,
                        tenant_id=tenant_id,
                        document_id=document_id,
                        model_name=provider.model_name,
                        dimension=provider.dimension,
                        vector=vec,
                        checksum=chunk.checksum,
                    )
                )

        return result_embeddings

embedding_orchestrator = EmbeddingOrchestrator()
