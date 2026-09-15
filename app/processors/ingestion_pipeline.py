"""
Shared Ingestion -> Chunk -> Embed -> Store Pipeline
=====================================================
The real Module 1->2 chain (parent-child semantic chunking, multi-dimensional chunk
scoring, BGE embedding, pgvector persistence) as a single reusable async function.

This exists because the equivalent logic in app/workers/tasks/embedding_tasks.py is
only ever reachable via a Celery `.delay()` call that nothing in the codebase actually
makes (no call sites, and no Celery broker is running locally anyway, since that needs
Redis). A document landing in `documents` without ever being chunked/embedded is
write-only — it can never be retrieved in chat. This function is called directly
(in-process, no worker needed) from every real ingestion entry point so that "ingested"
actually means "retrievable."
"""
import asyncio
import logging
from typing import Dict, Any

from sqlalchemy import text
from app.db.database import async_session_factory
from app.processors.semantic_chunker import semantic_chunker
from app.processors.chunk_validator import chunk_validator
from app.embeddings.embedding_orchestrator import embedding_orchestrator
from app.db.chunk_vector_repo import chunk_vector_repo

logger = logging.getLogger("company_brain.ingestion_pipeline")


async def chunk_embed_and_store(
    tenant_id: str,
    document_id: str,
    full_text: str,
    resource_category: str = "document",
) -> Dict[str, Any]:
    """Runs the real chunk -> score -> embed -> persist chain for one document's full
    text, so it becomes retrievable by hybrid_retriever immediately after this returns.
    """
    if not full_text or not full_text.strip():
        return {"status": "skipped", "reason": "empty text", "chunks_stored": 0, "vectors_stored": 0}

    # semantic_chunker generates fresh random chunk_ids on every call, so re-ingesting
    # the same document (e.g. a repeat connector sync) would otherwise silently
    # accumulate duplicate chunks/embeddings forever instead of replacing them —
    # duplicates then pollute retrieval candidate pools. Make re-ingestion idempotent:
    # clear this document's old chunks first (embeddings cascade-delete with them).
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        await session.execute(
            text("DELETE FROM document_chunks WHERE tenant_id = :tid AND document_id = :doc_id"),
            {"tid": tenant_id, "doc_id": document_id},
        )
        await session.commit()

    # semantic_chunker/embedding_orchestrator are synchronous/CPU-bound (regex parsing,
    # BGE model inference) — offload so this doesn't block the event loop for every
    # concurrent request, matching the pattern already used for retrieval-side embedding.
    raw_chunks = await asyncio.to_thread(
        semantic_chunker.chunk_document, tenant_id, document_id, full_text, resource_category
    )
    valid_chunks, rejected = chunk_validator.validate_and_score_chunks(raw_chunks)

    if not valid_chunks:
        logger.warning(
            f"[IngestionPipeline] document={document_id} produced 0 valid chunks "
            f"out of {len(raw_chunks)} raw chunks ({len(rejected)} rejected)."
        )
        return {
            "status": "no_valid_chunks", "chunks_stored": 0, "vectors_stored": 0,
            "raw_chunk_count": len(raw_chunks), "rejected_reasons": rejected[:10],
        }

    vectors = await asyncio.to_thread(
        embedding_orchestrator.generate_embeddings_for_chunks, tenant_id, document_id, valid_chunks
    )

    await chunk_vector_repo.save_chunks_and_embeddings(
        tenant_id=tenant_id, document_id=document_id, chunks=valid_chunks, embeddings=vectors,
    )

    logger.info(
        f"[IngestionPipeline] document={document_id}: {len(valid_chunks)} chunks, "
        f"{len(vectors)} vectors stored and now retrievable."
    )
    return {"status": "completed", "chunks_stored": len(valid_chunks), "vectors_stored": len(vectors)}
