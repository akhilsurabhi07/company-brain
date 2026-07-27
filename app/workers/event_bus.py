import json
from typing import Any, Dict, Optional
from app.config import settings

try:
    import redis
    _redis_available = True
except ImportError:
    _redis_available = False

class EventBus:
    """
    Decoupled Event Bus (Redis Streams / In-Memory Queue).
    Drives event-based pipeline orchestration:
      - document.created   ──▶ Ingestion Worker
      - document.extracted ──▶ Chunking Worker
      - document.chunked   ──▶ Embedding Worker
      - document.embedded  ──▶ Entity/Graph Worker
      - graph.enriched     ──▶ Indexing Complete
    """

    STREAM_KEY = "company_brain:pipeline_events"

    def __init__(self):
        self.redis_client = None
        if _redis_available:
            try:
                self.redis_client = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    decode_responses=True,
                )
            except Exception:
                self.redis_client = None

    def publish_event(
        self,
        event_type: str,  # 'document.created', 'document.extracted', 'document.chunked', 'document.embedded', 'graph.enriched'
        tenant_id: str,
        document_id: str,
        source_app: str,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Publishes pipeline lifecycle event to Redis Stream."""
        message_data = {
            "event_type": event_type,
            "tenant_id": str(tenant_id),
            "document_id": str(document_id),
            "source_app": str(source_app),
            "payload": json.dumps(extra_payload or {}),
        }
        if self.redis_client:
            try:
                message_id = self.redis_client.xadd(self.STREAM_KEY, message_data)
                return message_id
            except Exception as e:
                print(f"[EventBus Warning] Redis Stream publish error: {e}")
                return "offline_stream_id"
        return "offline_stream_id"

event_bus = EventBus()
