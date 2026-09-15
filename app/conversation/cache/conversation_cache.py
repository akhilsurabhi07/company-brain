"""Subsystem 19: Multi-Key Hash Conversation Response Cache."""

import hashlib
import json
import logging
from typing import Dict, Optional
import redis.asyncio as aioredis
from app.config import settings
from app.conversation.domain.response_payload import MultimodalResponsePayload

logger = logging.getLogger(__name__)

class ConversationCache:
    """Caches LLM response payloads using multi-key SHA-256 hashes via Redis."""

    def __init__(self):
        self._store: Dict[str, MultimodalResponsePayload] = {}
        self.redis_client = None

    async def _get_redis(self):
        if self.redis_client is not None:
            return self.redis_client
        try:
            # Real bug found via live Redis verification 2026-08-24 — same
            # root cause and same fix as app/security/rate_limiter.py's
            # _get_redis(): the real, measured one-time cold-connection cost
            # against the real Redis instance now running is ~2.0-2.1s;
            # every call after that on the same client is ~0.000s. 1.5s was
            # tighter than that real cost, so the cache's first use each
            # process lifetime always timed out.
            self.redis_client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=4.0,
                socket_connect_timeout=4.0
            )
            return self.redis_client
        except Exception as ex:
            logger.warning(f"Failed to initialize Redis connection: {ex}")
            return None

    @staticmethod
    def generate_cache_key(
        prompt_hash: str,
        knowledge_context_version: str,
        prompt_version: str,
        persona: str,
        tenant_id: str,
        provider: str = "default",
    ) -> str:
        raw = f"{prompt_hash}:{knowledge_context_version}:{prompt_version}:{persona}:{tenant_id}:{provider}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def get(self, cache_key: str) -> Optional[MultimodalResponsePayload]:
        redis_key = f"chat_cache:{cache_key}"
        r = await self._get_redis()
        if r is not None:
            try:
                cached_data = await r.get(redis_key)
                if cached_data:
                    return MultimodalResponsePayload.model_validate_json(cached_data)
            except Exception as e:
                logger.error(f"Redis get error: {e}")
        # Fallback
        return self._store.get(cache_key)

    async def set(self, cache_key: str, payload: MultimodalResponsePayload) -> None:
        redis_key = f"chat_cache:{cache_key}"
        r = await self._get_redis()
        if r is not None:
            try:
                # Cache for 24 hours
                await r.setex(redis_key, 86400, payload.model_dump_json())
                return
            except Exception as e:
                logger.error(f"Redis set error: {e}")
        # Fallback
        self._store[cache_key] = payload
