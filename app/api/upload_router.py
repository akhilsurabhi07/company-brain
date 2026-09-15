"""
Company Brain — Browser File Upload & Ingestion Router
Accepts PDF, DOCX, TXT, CSV, XLSX, and images (PNG/JPG/etc., via OCR) from the UI
and ingests them into the knowledge base.
"""

import io
import json
import uuid
import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token

logger = logging.getLogger("company_brain.upload")

router = APIRouter(prefix="/api/v1/upload", tags=["Browser File Upload"])

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp")

# Self-hosted OCR (EasyOCR — PyTorch-based, same self-hosted-model philosophy as
# BGEEmbedder/the cross-encoder reranker; no external API call, no system Tesseract
# binary required, unlike pytesseract). The reader loads real detection+recognition
# models the first time it's used and is expensive to construct, so it's built once
# and reused — same caching pattern as bge_embedder's model.
_ocr_reader = None


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import sys
        import easyocr
        # EasyOCR's first-run model download writes a Unicode block character ('█')
        # to stdout/stderr as its progress bar fill. Windows' default console codec
        # (cp1252/'charmap') can't encode that and raises UnicodeEncodeError, crashing
        # the whole request on the very first OCR call on a fresh machine — a real bug,
        # not a hypothetical one (reproduced during this session's own testing).
        # Reconfigure to UTF-8 with lossy fallback so a library's own console output
        # can never crash the request that triggered it.
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass
        logger.info("[OCR] Loading EasyOCR (en) model — first call only, cached afterward.")
        _ocr_reader = easyocr.Reader(["en"], gpu=False)
    return _ocr_reader


def ocr_image_bytes(content: bytes) -> str:
    """Runs real OCR over image bytes and returns the recognized text. Returns ''
    (not a fabricated placeholder) if the model finds no readable text."""
    reader = _get_ocr_reader()
    results = reader.readtext(content, detail=0, paragraph=True)
    return "\n".join(r.strip() for r in results if r and r.strip())


def ocr_scanned_pdf(content: bytes) -> str:
    """Rasterizes each PDF page (via PyMuPDF — no external poppler binary needed)
    and OCRs it. Used only as a fallback when the PDF has no extractable text layer
    (i.e. it's scanned pages/images, not real text)."""
    import pymupdf
    reader = _get_ocr_reader()
    doc = pymupdf.open(stream=content, filetype="pdf")
    page_texts = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        results = reader.readtext(img_bytes, detail=0, paragraph=True)
        page_texts.append("\n".join(r.strip() for r in results if r and r.strip()))
    doc.close()
    return "\n".join(page_texts)


def extract_text_from_file(filename: str, content: bytes) -> str:
    """Extract plain text from uploaded file based on its extension."""
    fname = filename.lower()

    # Plain text / Markdown / CSV
    if fname.endswith((".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml")):
        return content.decode("utf-8", errors="ignore")

    # PDF (real text layer first; falls back to real OCR only if the PDF turns out
    # to be scanned/image-based with no text layer — never fabricates content either way)
    if fname.endswith(".pdf"):
        extracted = ""
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            extracted = "\n".join(pages)
        except ImportError:
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    extracted = "\n".join(p.extract_text() or "" for p in pdf.pages)
            except ImportError:
                return f"[PDF file: {filename} — install PyPDF2 or pdfplumber to extract text]"

        # A real text-layer PDF yields far more than a few dozen characters; this
        # little text is the signature of a scanned/image-only PDF with no text layer.
        if len(extracted.strip()) < 40:
            try:
                ocr_text = ocr_scanned_pdf(content)
                if ocr_text.strip():
                    logger.info(f"[Upload] '{filename}': no text layer found, used OCR fallback ({len(ocr_text)} chars).")
                    return ocr_text
            except ImportError:
                return extracted + f"\n[Note: '{filename}' appears to be a scanned/image-based PDF with no text layer — install easyocr and pymupdf to OCR it]"
            except Exception as e:
                logger.warning(f"[Upload] scanned-PDF OCR fallback failed for '{filename}': {e}")
        return extracted

    # Word DOCX
    if fname.endswith(".docx"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            return f"[DOCX file: {filename} — install python-docx to extract text]"

    # Excel XLSX / XLS
    if fname.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            rows = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    row_text = " | ".join(str(c) for c in row if c is not None)
                    if row_text.strip():
                        rows.append(row_text)
            return "\n".join(rows)
        except ImportError:
            return f"[XLSX file: {filename} — install openpyxl to extract text]"

    # Images — screenshots, whiteboards, diagrams, slides (real OCR, not a stub)
    if fname.endswith(IMAGE_EXTENSIONS):
        try:
            ocr_text = ocr_image_bytes(content)
            return ocr_text if ocr_text.strip() else f"[Image file: {filename} — OCR ran but found no readable text]"
        except ImportError:
            return f"[Image file: {filename} — install easyocr to extract text via OCR]"
        except Exception as e:
            logger.error(f"[Upload] OCR failed for '{filename}': {e}")
            return f"[Image file: {filename} — OCR failed: {e}]"

    return f"[Unsupported file type: {filename}]"


@router.post("/document")
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: str = Form(default=""),
    source_label: Optional[str] = Form(default="UPLOAD"),
    token=Depends(require_authenticated_tenant),
):
    """
    Upload a document from the browser and ingest it into Company Brain.
    Supports: PDF (including scanned/image-only, via OCR fallback), DOCX, TXT, CSV,
    XLSX, MD, and images (PNG/JPG/BMP/TIFF/WEBP — via real OCR).

    Runs the same real storage + chunk/embed pipeline as connector-sourced documents:
    S3 (raw) + `documents` (metadata/content) -> semantic_chunker -> embedding_orchestrator
    -> `document_chunks`/`embeddings` (chunk_vector_repo). A document is not "ingested"
    until it's actually retrievable, so this endpoint doesn't return success until the
    real chunk/embed/store steps have completed.
    """
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10MB.")

    filename = file.filename or "uploaded_file.txt"
    logger.info(f"[Upload] Received file: {filename} ({len(content)} bytes) for tenant {tenant_id}")

    # extract_text_from_file can now run real OCR model inference (EasyOCR), which is
    # CPU-bound and meaningfully slower than plain text parsing — offload it so it
    # doesn't block the event loop for other concurrent requests, matching the pattern
    # already used for BGE embedding / cross-encoder reranking.
    text_content = await asyncio.to_thread(extract_text_from_file, filename, content)
    # Real bug found via live production-readiness audit 2026-08-31: uploading a
    # .exe (or any other unsupported type, or a PDF/DOCX/XLSX when the extraction
    # library isn't installed, or an image OCR failure) was reported as
    # "Upload Successful! ... 1 knowledge chunks created" — because
    # extract_text_from_file's own failure paths all return a synthetic, non-
    # empty bracketed placeholder string (e.g. "[Unsupported file type: x.exe]"),
    # which passed the emptiness check below and got stored/chunked/embedded as
    # if it were the file's real content. Every one of those placeholder strings
    # is constructed to start with "[" once stripped (the one legitimate
    # exception — a scanned PDF with no OCR libs that still has a few characters
    # of a real, if short, text layer — prepends that real text first, so it
    # does NOT start with "[" and is correctly still accepted here).
    stripped = text_content.strip()
    if not stripped or stripped.startswith("["):
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract real content from '{filename}': {stripped or 'no text found'}",
        )

    try:
        from app.db.database import async_session_factory
        from app.storage.s3_storage import s3_storage
        from app.processors.pii_redactor import pii_redactor
        from app.processors.ingestion_pipeline import chunk_embed_and_store

        source_app = (source_label or "upload").lower()
        doc_id = str(uuid.uuid4())
        clean_content = pii_redactor.redact_secrets(text_content)

        s3_key, file_size = await asyncio.to_thread(
            s3_storage.save_raw_json,
            tenant_id=tenant_id, source_app=source_app, resource_type="file_upload",
            external_id=doc_id, raw_payload={"filename": filename, "content": text_content},
        )

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            await session.execute(
                text("""
                    INSERT INTO documents (
                        id, tenant_id, source_app, resource_category, resource_type, external_id,
                        title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                    ) VALUES (
                        :id, :tenant_id, :source_app, 'document', 'file_upload', :external_id,
                        :title, :content, :s3_bucket, :s3_key, TRUE, :file_size
                    )
                """),
                {
                    "id": doc_id, "tenant_id": tenant_id, "source_app": source_app,
                    "external_id": doc_id, "title": filename, "content": clean_content,
                    "s3_bucket": s3_storage.bucket_name, "s3_key": s3_key, "file_size": file_size,
                },
            )
            await session.commit()

        pipeline_result = await chunk_embed_and_store(
            tenant_id=tenant_id, document_id=doc_id, full_text=clean_content, resource_category="document",
        )
        if pipeline_result["status"] != "completed":
            raise HTTPException(
                status_code=422,
                detail=f"File was stored but produced no retrievable content: {pipeline_result}",
            )

        logger.info(f"[Upload] Successfully ingested '{filename}': {pipeline_result}")

        # Real audit trail found+fixed 2026-08-23: this endpoint — the actual
        # live path every real user upload goes through — never wrote to any
        # audit table at all. `ingestion_audit_logs` already existed in the
        # real schema and had a real reader (the new Admin Dashboard activity
        # endpoint), but its only prior writer was inside the separate
        # Gateway module, unreachable from this endpoint. Without this, the
        # Admin Dashboard's activity log would be honestly-empty forever for
        # every tenant that only ever used manual upload (i.e. every real
        # browser user this whole engagement has tested with).
        try:
            async with async_session_factory() as audit_session:
                await audit_session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
                await audit_session.execute(
                    text("""
                        INSERT INTO ingestion_audit_logs (tenant_id, source_app, action, items_processed, details)
                        VALUES (:tid, :src, 'document_upload', :items, :details)
                    """),
                    {
                        "tid": tenant_id, "src": source_app, "items": pipeline_result["chunks_stored"],
                        "details": json.dumps({"filename": filename, "document_id": doc_id}),
                    },
                )
                await audit_session.commit()
        except Exception as audit_ex:
            # An audit-log write failure must never fail the upload itself —
            # the document is already safely stored by this point.
            logger.warning(f"[Upload] Audit log write failed (non-fatal): {audit_ex}")

        return JSONResponse({
            "status": "success",
            "filename": filename,
            "document_id": doc_id,
            "chunks_ingested": pipeline_result["chunks_stored"],
            "vectors_stored": pipeline_result["vectors_stored"],
            "tenant_id": tenant_id,
            "message": f"✅ '{filename}' ingested successfully into Company Brain! ({pipeline_result['chunks_stored']} knowledge chunks created)"
        })

    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"[Upload] Ingestion failed: {ex}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(ex)}")


@router.get("/stats")
async def get_ingestion_stats(tenant_id: str = "", token=Depends(require_authenticated_tenant)):
    """Return document count and source breakdown for the admin dashboard."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    try:
        from app.db.database import async_session_factory

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})

            total_res = await session.execute(
                text("SELECT COUNT(*) FROM documents WHERE tenant_id = :tid"),
                {"tid": tenant_id}
            )
            total = total_res.scalar() or 0

            source_res = await session.execute(
                text("""
                    SELECT source_app, COUNT(*) as cnt
                    FROM documents WHERE tenant_id = :tid
                    GROUP BY source_app ORDER BY cnt DESC
                """),
                {"tid": tenant_id}
            )
            sources = [{"source": r[0], "count": r[1]} for r in source_res.fetchall()]

            recent_res = await session.execute(
                text("""
                    SELECT title, created_at FROM documents
                    WHERE tenant_id = :tid
                    ORDER BY created_at DESC LIMIT 10
                """),
                {"tid": tenant_id}
            )
            # Real bug found via live Admin Dashboard testing 2026-08-23: plain
            # Python str(datetime) produces a space-separated, non-ISO string
            # ("2026-08-23 21:41:07.123456+00:00") that JavaScript's Date
            # constructor can't reliably parse — the admin dashboard's "Recently
            # Ingested Documents" list showed every real document as "Invalid
            # Date". .isoformat() matches every other real endpoint's convention
            # in this codebase and parses correctly in the browser.
            recent = [{"title": r[0], "created_at": r[1].isoformat() if r[1] else None} for r in recent_res.fetchall()]

        return {
            "total_documents": total,
            "sources": sources,
            "recent_documents": recent
        }
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))
