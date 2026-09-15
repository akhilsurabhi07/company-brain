import json
from typing import Any, Dict, Optional
from sqlalchemy import text
from app.db.database import async_session_factory
from app.domain.models import ExtractedDocument, ExtractedTable, ExtractedImage, ExtractedSection, ExtractedPage, ExtractedOCR

class ExtractedDocumentRepository:
    """
    Principal YC-Scale Repository for Document Intelligence Layer:
      - document_processing_jobs (State Machine, Worker Retries, Execution Telemetry)
      - document_pages (Page-level PDF / Document Navigation)
      - document_sections (Hierarchical Headings & Token Counts)
      - document_tables (Multi-Format Markdown Grids, Structured JSON, CSV)
      - document_images (Embedded Assets & Object Hashes)
      - document_ocr (Decoupled OCR Engine Results)
      - document_metadata (Enterprise Governance, Language, Retention Policies)
    Enforces PostgreSQL Row-Level Security (RLS) tenant isolation across ALL tables.
    """

    async def update_job_status(
        self,
        tenant_id: str,
        document_id: str,
        pipeline_stage: str,
        status: str,
        priority: int = 50,
        worker_id: Optional[str] = None,
        error_message: Optional[str] = None,
        execution_time_ms: int = 0,
    ):
        """Updates the processing pipeline state machine for progress tracking, priority queues, and retries."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
            await session.execute(
                text("""
                    INSERT INTO document_processing_jobs (
                        tenant_id, document_id, pipeline_stage, status, priority, worker_id, error_message, execution_time_ms, updated_at
                    ) VALUES (
                        :tenant_id, :document_id, :pipeline_stage, :status, :priority, :worker_id, :error_message, :execution_time_ms, now()
                    ) ON CONFLICT (tenant_id, document_id) DO UPDATE
                    SET pipeline_stage = EXCLUDED.pipeline_stage,
                        status = EXCLUDED.status,
                        priority = EXCLUDED.priority,
                        worker_id = EXCLUDED.worker_id,
                        error_message = EXCLUDED.error_message,
                        execution_time_ms = EXCLUDED.execution_time_ms,
                        updated_at = now(),
                        completed_at = CASE WHEN EXCLUDED.status = 'completed' THEN now() ELSE document_processing_jobs.completed_at END
                """),
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "pipeline_stage": pipeline_stage,
                    "status": status,
                    "priority": priority,
                    "worker_id": worker_id,
                    "error_message": error_message,
                    "execution_time_ms": execution_time_ms,
                },
            )
            await session.commit()

    async def save_extracted_document(self, extracted_doc: ExtractedDocument) -> str:
        """
        Persists ExtractedDocument into normalized Document Intelligence relational tables under current_tenant_id session.
        """
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(extracted_doc.tenant_id)})

            # 1. Update Parent Document Clean Content
            await session.execute(
                text("""
                    UPDATE documents
                    SET content = :clean_text, updated_at = now()
                    WHERE tenant_id = :tenant_id AND id = :document_id
                """),
                {
                    "tenant_id": extracted_doc.tenant_id,
                    "document_id": extracted_doc.document_id,
                    "clean_text": extracted_doc.clean_text,
                },
            )

            # 2. Persist Governance Metadata
            source_connector = extracted_doc.source.split(":")[0] if ":" in extracted_doc.source else "generic"
            await session.execute(
                text("""
                    INSERT INTO document_metadata (
                        tenant_id, document_id, checksum, source_connector, language, mime_type, file_size_bytes, custom_metadata, extracted_at
                    ) VALUES (
                        :tenant_id, :document_id, :checksum, :source_connector, :language, :mime_type, :file_size_bytes, :custom_metadata, now()
                    ) ON CONFLICT (tenant_id, document_id) DO UPDATE
                    SET checksum = EXCLUDED.checksum,
                        source_connector = EXCLUDED.source_connector,
                        language = EXCLUDED.language,
                        mime_type = EXCLUDED.mime_type,
                        file_size_bytes = EXCLUDED.file_size_bytes,
                        custom_metadata = EXCLUDED.custom_metadata,
                        extracted_at = now()
                """),
                {
                    "tenant_id": extracted_doc.tenant_id,
                    "document_id": extracted_doc.document_id,
                    "checksum": extracted_doc.checksum,
                    "source_connector": source_connector,
                    "language": extracted_doc.metadata.get("language", "en"),
                    "mime_type": extracted_doc.metadata.get("mime_type", "application/octet-stream"),
                    "file_size_bytes": extracted_doc.metadata.get("file_size_bytes", len(extracted_doc.clean_text)),
                    "custom_metadata": json.dumps(extracted_doc.metadata),
                },
            )

            # 3. Clean and Insert Document Pages
            await session.execute(
                text("DELETE FROM document_pages WHERE tenant_id = :t_id AND document_id = :d_id"),
                {"t_id": extracted_doc.tenant_id, "d_id": extracted_doc.document_id},
            )
            for page_idx, pg in enumerate(extracted_doc.pages, start=1):
                await session.execute(
                    text("""
                        INSERT INTO document_pages (
                            tenant_id, document_id, page_number, width, height, page_text, layout_bbox
                        ) VALUES (
                            :tenant_id, :document_id, :page_number, :width, :height, :page_text, :layout_bbox
                        )
                    """),
                    {
                        "tenant_id": extracted_doc.tenant_id,
                        "document_id": extracted_doc.document_id,
                        "page_number": pg.page_number or page_idx,
                        "width": pg.width,
                        "height": pg.height,
                        "page_text": pg.page_text,
                        "layout_bbox": json.dumps(pg.layout_bbox),
                    },
                )

            # 4. Clean and Insert Document Sections
            await session.execute(
                text("DELETE FROM document_sections WHERE tenant_id = :t_id AND document_id = :d_id"),
                {"t_id": extracted_doc.tenant_id, "d_id": extracted_doc.document_id},
            )
            for idx, sec in enumerate(extracted_doc.sections, start=1):
                token_count = len(sec.content.split())
                await session.execute(
                    text("""
                        INSERT INTO document_sections (
                            tenant_id, document_id, section_order, heading, level, content, token_count
                        ) VALUES (
                            :tenant_id, :document_id, :section_order, :heading, :level, :content, :token_count
                        )
                    """),
                    {
                        "tenant_id": extracted_doc.tenant_id,
                        "document_id": extracted_doc.document_id,
                        "section_order": idx,
                        "heading": sec.heading,
                        "level": sec.level,
                        "content": sec.content,
                        "token_count": token_count,
                    },
                )

            # 5. Clean and Insert Document Tables (JSON + Markdown Grid + CSV)
            await session.execute(
                text("DELETE FROM document_tables WHERE tenant_id = :t_id AND document_id = :d_id"),
                {"t_id": extracted_doc.tenant_id, "d_id": extracted_doc.document_id},
            )
            for idx, tbl in enumerate(extracted_doc.tables, start=1):
                rows_count = len(tbl.data_json)
                cols_count = len(tbl.data_json[0].keys()) if rows_count > 0 else 0
                await session.execute(
                    text("""
                        INSERT INTO document_tables (
                            tenant_id, document_id, table_number, page_number, rows_count, cols_count, grid_markdown, data_json, confidence
                        ) VALUES (
                            :tenant_id, :document_id, :table_number, :page_number, :rows_count, :cols_count, :grid_markdown, :data_json, :confidence
                        )
                    """),
                    {
                        "tenant_id": extracted_doc.tenant_id,
                        "document_id": extracted_doc.document_id,
                        "table_number": idx,
                        "page_number": tbl.page_number or 1,
                        "rows_count": rows_count,
                        "cols_count": cols_count,
                        "grid_markdown": tbl.grid_markdown,
                        "data_json": json.dumps(tbl.data_json),
                        "confidence": tbl.confidence,
                    },
                )

            # 6. Clean and Insert Document Images & Decoupled OCR
            await session.execute(
                text("DELETE FROM document_images WHERE tenant_id = :t_id AND document_id = :d_id"),
                {"t_id": extracted_doc.tenant_id, "d_id": extracted_doc.document_id},
            )
            for idx, img in enumerate(extracted_doc.images, start=1):
                await session.execute(
                    text("""
                        INSERT INTO document_images (
                            tenant_id, document_id, image_index, page_number, mime_type, s3_key, width, height
                        ) VALUES (
                            :tenant_id, :document_id, :image_index, :page_number, :mime_type, :s3_key, :width, :height
                        )
                    """),
                    {
                        "tenant_id": extracted_doc.tenant_id,
                        "document_id": extracted_doc.document_id,
                        "image_index": idx,
                        "page_number": img.page_number or 1,
                        "mime_type": img.mime_type,
                        "s3_key": img.s3_key,
                        "width": img.width,
                        "height": img.height,
                    },
                )

            # 7. Update Job Status to 'completed'
            await self.update_job_status(
                tenant_id=extracted_doc.tenant_id,
                document_id=extracted_doc.document_id,
                pipeline_stage="extracting",
                status="completed",
                priority=50,
            )

            await session.commit()
            return extracted_doc.document_id

    async def get_extracted_document(self, tenant_id: str, document_id: str) -> Optional[ExtractedDocument]:
        """
        Queries ExtractedDocument by joining normalized tables under RLS policy.
        """
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})

            # Fetch Parent Document Clean Content
            doc_res = await session.execute(
                text("SELECT content FROM documents WHERE tenant_id = :tenant_id AND id = :document_id"),
                {"tenant_id": tenant_id, "document_id": document_id},
            )
            doc_row = doc_res.fetchone()
            if not doc_row:
                return None
            clean_text = doc_row[0] or ""

            # Fetch Metadata
            meta_res = await session.execute(
                text("SELECT checksum, source_connector, custom_metadata, extracted_at FROM document_metadata WHERE tenant_id = :t_id AND document_id = :d_id"),
                {"t_id": tenant_id, "d_id": document_id},
            )
            meta_row = meta_res.fetchone()
            checksum = meta_row[0] if meta_row else ""
            source = meta_row[1] if meta_row else f"doc:{document_id}"
            metadata = json.loads(meta_row[2] or "{}") if (meta_row and isinstance(meta_row[2], str)) else (meta_row[2] if meta_row else {})
            extracted_at = str(meta_row[3]) if meta_row and meta_row[3] else ""

            # Fetch Pages
            pg_res = await session.execute(
                text("SELECT page_number, width, height, page_text, layout_bbox FROM document_pages WHERE tenant_id = :t_id AND document_id = :d_id ORDER BY page_number ASC"),
                {"t_id": tenant_id, "d_id": document_id},
            )
            pages = [
                ExtractedPage(page_number=r[0], width=r[1], height=r[2], page_text=r[3] or "", layout_bbox=r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"))
                for r in pg_res.fetchall()
            ]

            # Fetch Sections
            sec_res = await session.execute(
                text("SELECT heading, level, content, token_count FROM document_sections WHERE tenant_id = :t_id AND document_id = :d_id ORDER BY section_order ASC"),
                {"t_id": tenant_id, "d_id": document_id},
            )
            sections = [
                ExtractedSection(section_id=f"sec_{i+1}", heading=r[0], level=r[1], content=r[2], token_count=r[3] or 0)
                for i, r in enumerate(sec_res.fetchall())
            ]

            # Fetch Tables
            tbl_res = await session.execute(
                text("SELECT page_number, table_number, rows_count, cols_count, grid_markdown, data_json, confidence FROM document_tables WHERE tenant_id = :t_id AND document_id = :d_id ORDER BY table_number ASC"),
                {"t_id": tenant_id, "d_id": document_id},
            )
            tables = [
                ExtractedTable(
                    table_id=f"tbl_{i+1}",
                    page_number=r[0],
                    table_number=r[1],
                    rows_count=r[2] or 0,
                    cols_count=r[3] or 0,
                    grid_markdown=r[4],
                    data_json=r[5] if isinstance(r[5], list) else json.loads(r[5] or "[]"),
                    confidence=r[6] or 1.0,
                )
                for i, r in enumerate(tbl_res.fetchall())
            ]

            # Fetch Images
            img_res = await session.execute(
                text("SELECT page_number, image_index, mime_type, s3_key, width, height FROM document_images WHERE tenant_id = :t_id AND document_id = :d_id ORDER BY image_index ASC"),
                {"t_id": tenant_id, "d_id": document_id},
            )
            images = [
                ExtractedImage(
                    image_id=f"img_{i+1}",
                    page_number=r[0],
                    image_index=r[1],
                    mime_type=r[2],
                    s3_key=r[3],
                    width=r[4],
                    height=r[5],
                )
                for i, r in enumerate(img_res.fetchall())
            ]

            return ExtractedDocument(
                tenant_id=tenant_id,
                document_id=document_id,
                clean_text=clean_text,
                pages=pages,
                sections=sections,
                tables=tables,
                images=images,
                captions=[],
                metadata=metadata,
                source=source,
                checksum=checksum,
                timestamps={"extracted_at": extracted_at},
            )

extracted_doc_repo = ExtractedDocumentRepository()
