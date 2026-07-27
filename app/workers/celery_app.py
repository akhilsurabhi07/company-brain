from app.config import settings
from app.storage.s3_storage import s3_storage
from app.processors.pii_redactor import pii_redactor
from app.workers.event_bus import event_bus

try:
    from celery import Celery

    celery_app = Celery(
        "company_brain_workers",
        broker=settings.REDIS_URL,
        backend=settings.REDIS_URL,
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_routes={
            "ingest_resource_task": {"queue": "ingestion_queue"},
            "tasks.extraction.process_document": {"queue": "extraction"},
            "tasks.ocr.process_image": {"queue": "ocr"},
        },
    )
except ImportError:
    class DummyCelery:
        def task(self, *args, **kwargs):
            def decorator(fn):
                fn.delay = fn
                return fn
            return decorator

    celery_app = DummyCelery()

@celery_app.task(name="ingest_resource_task", bind=True, max_retries=3)
def ingest_resource_task(
    self,
    tenant_id: str,
    source_app: str,
    resource_category: str,
    resource_type: str,
    external_id: str,
    title: str,
    content: str,
    raw_payload: dict,
):
    """
    Celery task handling asynchronous ingestion:
    1. Redacts PII & API keys from content.
    2. Writes Zstandard compressed JSON raw payload to AWS S3 / MinIO.
    3. Emits 'document.created' event to Redis Streams for Phase 2.
    """
    try:
        # 1. Redact secrets from text content
        clean_content = pii_redactor.redact_secrets(content)

        # 2. Write raw payload to S3 with .json.zst compression
        s3_key, file_bytes_len = s3_storage.save_raw_json(
            tenant_id=tenant_id,
            source_app=source_app,
            resource_type=resource_type,
            external_id=external_id,
            raw_payload=raw_payload,
            compress=True,
        )

        # 3. Publish ingestion event to Redis Stream
        event_bus.publish_event(
            event_type="document.created",
            tenant_id=tenant_id,
            document_id=external_id,
            source_app=source_app,
            extra_payload={
                "title": title,
                "s3_key": s3_key,
                "file_size": file_bytes_len,
            },
        )

        return {
            "status": "success",
            "s3_key": s3_key,
            "bytes_written": file_bytes_len,
        }

    except Exception as exc:
        if hasattr(self, "retry"):
            raise self.retry(exc=exc, countdown=10)
        raise exc
