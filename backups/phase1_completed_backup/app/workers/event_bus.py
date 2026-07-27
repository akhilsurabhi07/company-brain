import json
from typing import Any, Dict, Optional
import redis
from app.config import settings

class RedisEventBus:
    """
    Redis Streams Event Bus Producer.
    Emits real-time data events (document.created, document.updated, etc.)
    allowing Phase 2 vector embedding & search engines to consume updates asynchronously.
    """

    STREAM_KEY = "company_brain:ingestion_events"

    def __init__(self):
        self.redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
        )

    def publish_event(
        self,
        event_type: str,  # 'document.created', 'document.updated', 'document.deleted', 'acl.updated'
        tenant_id: str,
        document_id: str,
        source_app: str,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Publishes an ingestion event to Redis Stream."""
        message_data = {
            "event_type": event_type,
            "tenant_id": str(tenant_id),
            "document_id": str(document_id),
            "source_app": str(source_app),
            "payload": json.dumps(extra_payload or {}),
        }
        try:
            message_id = self.redis_client.xadd(self.STREAM_KEY, message_data)
            return message_id
        except Exception as e:
            # Fallback for offline/dev Redis
            print(f"[EventBus Warning] Redis Stream publish error: {e}")
            return "offline_stream_id"

event_bus = RedisEventBus()
