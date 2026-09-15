"""
Chunk & Vector Database Repository
=================================
Handles async persistence and queries for document_chunks and embeddings
tables under PostgreSQL Row-Level Security (RLS).
"""
import json
import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from app.db.database import async_session_factory
from app.interfaces.chunker_interface import DocumentChunk
from app.interfaces.embedding_interface import VectorEmbedding

class ChunkVectorRepository:
    """Asynchronous PostgreSQL Repository for Chunks & Vector Store."""

    async def save_chunks_and_embeddings(
        self,
        tenant_id: str,
        document_id: str,
        chunks: List[DocumentChunk],
        embeddings: List[VectorEmbedding],
    ) -> bool:
        """Persists chunks and vectors into AWS RDS PostgreSQL under tenant RLS."""
        if not chunks:
            return True

        async with async_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id}
            )

            # 1. Insert Chunks into document_chunks
            for c in chunks:
                await session.execute(
                    text("""
                        INSERT INTO document_chunks (
                            id, tenant_id, document_id, parent_chunk_id, page_id, section_id,
                            chunk_index, heading, text_content, token_count, char_count,
                            language_code, checksum, structural_score, semantic_score,
                            business_score, importance_score, metadata
                        ) VALUES (
                            :id, :tenant_id, :document_id, :parent_chunk_id, :page_id, :section_id,
                            :chunk_index, :heading, :text_content, :token_count, :char_count,
                            :language_code, :checksum, :structural_score, :semantic_score,
                            :business_score, :importance_score, :metadata
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            heading = EXCLUDED.heading,
                            text_content = EXCLUDED.text_content,
                            token_count = EXCLUDED.token_count,
                            importance_score = EXCLUDED.importance_score,
                            metadata = EXCLUDED.metadata;
                    """),
                    {
                        "id": c.chunk_id,
                        "tenant_id": tenant_id,
                        "document_id": document_id,
                        "parent_chunk_id": c.parent_chunk_id,
                        "page_id": c.page_id,
                        "section_id": c.section_id,
                        "chunk_index": c.chunk_order,
                        "heading": c.heading,
                        "text_content": c.text_content,
                        "token_count": c.token_count,
                        "char_count": c.char_count,
                        "language_code": c.language_code,
                        "checksum": c.checksum,
                        "structural_score": c.structural_score,
                        "semantic_score": c.semantic_score,
                        "business_score": c.business_score,
                        "importance_score": c.importance_score,
                        "metadata": json.dumps(c.metadata or {}),
                    },
                )

            # 2. Insert Vector Embeddings into embeddings table using column 'embedding'
            for idx, emb in enumerate(embeddings):
                vec_data = emb.vector if hasattr(emb, "vector") else emb
                emb_id = getattr(emb, "embedding_id", str(uuid.uuid4()))
                chunk_id = getattr(emb, "chunk_id", chunks[idx].chunk_id if idx < len(chunks) else str(uuid.uuid4()))
                model_name = getattr(emb, "model_name", "BAAI/bge-large-en-v1.5")
                dimension = getattr(emb, "dimension", len(vec_data))
                checksum = getattr(emb, "checksum", chunks[idx].checksum if idx < len(chunks) else "sha256_checksum")
                
                vector_str = f"[{','.join(str(x) for x in vec_data)}]"
                await session.execute(
                    text("""
                        INSERT INTO embeddings (
                            id, tenant_id, document_id, chunk_id, model_name, dimension, embedding, checksum
                        ) VALUES (
                            :id, :tenant_id, :document_id, :chunk_id, :model_name, :dimension, CAST(:vec_val AS vector), :checksum
                        )
                        ON CONFLICT (tenant_id, chunk_id, model_name) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            checksum = EXCLUDED.checksum,
                            created_at = CURRENT_TIMESTAMP;
                    """),
                    {
                        "id": emb_id,
                        "tenant_id": tenant_id,
                        "document_id": document_id,
                        "chunk_id": chunk_id,
                        "model_name": model_name,
                        "dimension": dimension,
                        "vec_val": vector_str,
                        "checksum": checksum,
                    },
                )

            await session.commit()
            return True

    async def execute_vector_similarity_search(
        self, tenant_id: str, query_vector: List[float], top_k: int = 5, model_name: str = "BAAI/bge-large-en-v1.5"
    ) -> List[Dict[str, Any]]:
        """Executes Cosine Similarity search over embeddings using pgvector HNSW index under RLS."""
        vector_str = f"[{','.join(str(x) for x in query_vector)}]"

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})

            res = await session.execute(
                text("""
                    SELECT 
                        e.chunk_id,
                        e.document_id,
                        1 - (e.embedding <=> CAST(:qvec AS vector)) AS cosine_similarity,
                        c.heading,
                        c.text_content,
                        c.token_count,
                        c.importance_score,
                        c.parent_chunk_id,
                        d.title AS document_title
                    FROM embeddings e
                    JOIN document_chunks c ON e.chunk_id = c.id
                    JOIN documents d ON e.document_id = d.id
                    WHERE e.tenant_id = :tenant_id AND e.model_name = :model_name
                    ORDER BY e.embedding <=> CAST(:qvec AS vector) ASC
                    LIMIT :top_k;
                """),
                {"tenant_id": tenant_id, "qvec": vector_str, "model_name": model_name, "top_k": top_k},
            )

            results = []
            for row in res.fetchall():
                results.append(
                    {
                        "chunk_id": row[0],
                        "document_id": row[1],
                        "similarity_score": round(float(row[2]), 4),
                        "heading": row[3],
                        "text_content": row[4],
                        "token_count": row[5],
                        "importance_score": float(row[6]),
                        "parent_chunk_id": row[7],
                        "document_title": row[8],
                    }
                )

            return results

chunk_vector_repo = ChunkVectorRepository()
