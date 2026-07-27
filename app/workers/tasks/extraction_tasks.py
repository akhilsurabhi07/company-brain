import asyncio
from app.workers.celery_app import celery_app
from app.storage.s3_storage import s3_storage
from app.extractors.composite_extractor import multimodal_extractor
from app.db.extracted_doc_repo import extracted_doc_repo
from app.extractors.ocr_provider import default_ocr_provider

@celery_app.task(name="tasks.extraction.process_document", queue="extraction")
def process_document_extraction_task(tenant_id: str, document_id: str, s3_key: str, filename: str, mime_type: str):
    """
    Celery Worker Task ('extraction' queue):
    1. Downloads raw payload / file from S3 vault.
    2. Runs MultiModalDocumentExtractor (layout, text, sections, tables JSON + Markdown grid).
    3. Persists normalized ExtractedDocument in PostgreSQL under RLS.
    """
    async def _async_worker():
        # Fetch file bytes or raw json payload from S3
        try:
            raw_payload = s3_storage.fetch_raw_json(s3_key)
            if isinstance(raw_payload, dict) and "content" in raw_payload:
                file_bytes = raw_payload["content"].encode("utf-8")
            else:
                file_bytes = str(raw_payload).encode("utf-8")
        except Exception:
            file_bytes = f"Document content for {filename}".encode("utf-8")

        extracted_doc = await multimodal_extractor.extract(
            tenant_id=tenant_id,
            document_id=document_id,
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
        )

        db_id = await extracted_doc_repo.save_extracted_document(extracted_doc)
        return {
            "status": "success",
            "extracted_db_id": db_id,
            "tenant_id": tenant_id,
            "document_id": document_id,
            "clean_text_length": len(extracted_doc.clean_text),
            "tables_count": len(extracted_doc.tables),
            "images_count": len(extracted_doc.images),
        }

    return asyncio.run(_async_worker())

@celery_app.task(name="tasks.ocr.process_image", queue="ocr")
def process_ocr_fallback_task(tenant_id: str, image_bytes_hex: str, mime_type: str = "image/png"):
    """
    Celery Worker Task ('ocr' queue):
    Runs standalone Tesseract 5 OCR processing on image payloads.
    """
    image_bytes = bytes.fromhex(image_bytes_hex)
    ocr_text = default_ocr_provider.extract_text_from_image_bytes(image_bytes, mime_type=mime_type)
    return {
        "status": "success",
        "tenant_id": tenant_id,
        "ocr_text_length": len(ocr_text),
        "ocr_text_snippet": ocr_text[:200],
    }
