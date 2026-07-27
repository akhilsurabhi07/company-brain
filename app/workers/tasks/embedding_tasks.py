"""
Celery Background Worker Tasks — Embedding Pipeline
===================================================
Priority Queues:
  - embedding.high    : Interactive user uploads
  - embedding.normal  : Scheduled connector syncs
  - embedding.low     : Bulk re-indexing
"""
import asyncio
from typing import Dict, Any
from app.workers.celery_app import celery_app
from app.db.extracted_doc_repo import extracted_doc_repo
from app.processors.content_normalizer import content_normalizer
from app.processors.document_context_builder import document_context_builder
from app.processors.semantic_chunker import semantic_chunker
from app.processors.chunk_validator import chunk_validator
from app.embeddings.embedding_orchestrator import embedding_orchestrator
from app.db.chunk_vector_repo import chunk_vector_repo
from app.workers.event_bus import event_bus
from app.workers.telemetry import telemetry_logger

@celery_app.task(name="app.workers.tasks.embedding_tasks.process_document_embedding_task", queue="embedding")
def process_document_embedding_task(tenant_id: str, document_id: str, priority: int = 5) -> Dict[str, Any]:
    """
    Celery Task driving Module 2:
      Extracted Document ➔ Content Normalizer ➔ Context Builder ➔ Semantic Chunker
      ➔ Chunk Validator ➔ Embedding Orchestrator ➔ pgvector Store
    """
    async def _async_pipeline():
        # Update Job Status to 'chunking'
        await extracted_doc_repo.update_job_status(
            tenant_id=tenant_id,
            document_id=document_id,
            pipeline_stage="chunking",
            status="in_progress",
            priority=priority,
        )

        # 1. Fetch Extracted Document
        extracted_doc = await extracted_doc_repo.get_extracted_document(tenant_id, document_id)
        if not extracted_doc:
            await extracted_doc_repo.update_job_status(
                tenant_id=tenant_id,
                document_id=document_id,
                pipeline_stage="chunking",
                status="failed",
                error_message="Extracted document not found in database",
            )
            return {"status": "failed", "error": "Document not found"}

        # 2. Content Normalization
        normalized_doc = content_normalizer.normalize_document(extracted_doc)

        # 3. Document Context Tree Assembly
        context_tree = document_context_builder.build_context_tree(normalized_doc)

        # 4. Parent-Child Dual-Granularity Chunking
        raw_chunks = semantic_chunker.chunk_document(
            tenant_id=tenant_id,
            document_id=document_id,
            full_text=context_tree.full_context_text,
            resource_category="document",
        )

        # 5. Chunk Validation & Multi-Dimensional Scoring
        valid_chunks, reasons = chunk_validator.validate_and_score_chunks(raw_chunks)

        # Publish Versioned Event: document.chunked.v1
        event_bus.publish_event(
            event_type="document.chunked.v1",
            tenant_id=tenant_id,
            document_id=document_id,
            source_app="embedding_worker",
            extra_payload={"valid_chunks": len(valid_chunks), "rejected_chunks": len(reasons)},
        )

        # Update Job Status to 'embedding'
        await extracted_doc_repo.update_job_status(
            tenant_id=tenant_id,
            document_id=document_id,
            pipeline_stage="embedding",
            status="in_progress",
            priority=priority,
        )

        # 6. Embedding Orchestrator Batch Inference
        vectors = embedding_orchestrator.generate_embeddings_for_chunks(tenant_id, document_id, valid_chunks)

        # 7. PostgreSQL pgvector Store & RLS Persistence
        await chunk_vector_repo.save_chunks_and_embeddings(
            tenant_id=tenant_id, document_id=document_id, chunks=valid_chunks, embeddings=vectors
        )

        # Update Job Status to 'completed'
        await extracted_doc_repo.update_job_status(
            tenant_id=tenant_id,
            document_id=document_id,
            pipeline_stage="completed",
            status="completed",
            priority=priority,
        )

        # Publish Versioned Event: embedding.completed.v1
        event_bus.publish_event(
            event_type="embedding.completed.v1",
            tenant_id=tenant_id,
            document_id=document_id,
            source_app="embedding_worker",
            extra_payload={"chunks_stored": len(valid_chunks), "vectors_stored": len(vectors)},
        )

        # Telemetry Metrics Logging
        telemetry_logger.log_business_metrics(tenant_id, document_id, len(valid_chunks), len(vectors))

        return {
            "status": "completed",
            "document_id": document_id,
            "chunks_processed": len(valid_chunks),
            "vectors_generated": len(vectors),
        }

    return asyncio.run(_async_pipeline())
