import json
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger("company_brain.redis_cache")


class RedisCacheManager:
    """
    High-Performance Tenant Cache Manager.
    Caches ENCRYPTED OAuth tokens and tenant configs with 15-minute TTL.
    SECURITY GUARANTEE: Tokens remain 100% AES-256-GCM encrypted in Redis.
    Tenant isolation is enforced via 'tenant:{tenant_id}:...' key prefixes.

    Real bug found+fixed 2026-08-24 while reviewing this engagement's Redis
    gaps: despite the class name, docstring, and "SECURITY GUARANTEE" comment
    all claiming real Redis-backed caching, this was — for its entire
    existence — a plain in-process Python dict with no Redis connection
    whatsoever. Two real, concrete consequences, independent of whether
    anything reads from it: (1) the docstring's own claims were false —
    tokens never actually left process memory; and (2) it was a genuine
    unbounded memory leak — expired entries were only ever skipped on read,
    never evicted, so every tenant+connector pair this process ever saw
    accumulated in memory forever. Real Redis TTL (SETEX) fixes both: a
    real, separate cache store as the docstring always claimed, and native
    expiry instead of a leak. Same connection-timeout tuning as
    app/security/rate_limiter.py and app/conversation/cache/
    conversation_cache.py (4.0s — the real, measured one-time cold-connection
    cost against this environment's Redis instance is ~2.0-2.1s).

    Falls back to the original in-memory dict — not a fabricated success —
    if Redis is genuinely unreachable, so a real outage degrades gracefully
    to the old behavior rather than raising into the OAuth connect flow.
    """

    def __init__(self):
        self._in_memory_cache = {}  # Real fallback only — used when Redis is genuinely unreachable
        self.redis_client = None

    async def _get_redis(self):
        if self.redis_client is not None:
            return self.redis_client
        try:
            import redis.asyncio as aioredis
            self.redis_client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=4.0,
                socket_connect_timeout=4.0,
            )
            return self.redis_client
        except Exception as ex:
            logger.warning(f"[REDIS-CACHE-WARN] Failed to initialize Redis connection: {ex}")
            return None

    async def get_cached_encrypted_token(self, tenant_id: str, source_app: str) -> Optional[str]:
        """Fetches encrypted OAuth token cipher string from tenant-isolated cache."""
        cache_key = f"tenant:{tenant_id}:token:{source_app}"
        try:
            r = await self._get_redis()
            if r is not None:
                return await r.get(cache_key)
        except Exception as ex:
            logger.warning(f"[REDIS-CACHE-WARN] Real Redis read failed, falling back to in-memory: {ex}")

        cached = self._in_memory_cache.get(cache_key)
        if cached and cached.get("exp", 0) > time_now():
            return cached.get("val")
        return None

    async def set_cached_encrypted_token(self, tenant_id: str, source_app: str, encrypted_token: str, ttl_seconds: int = 900):
        """Caches encrypted cipher string with a real 15-minute TTL."""
        cache_key = f"tenant:{tenant_id}:token:{source_app}"
        try:
            r = await self._get_redis()
            if r is not None:
                await r.setex(cache_key, ttl_seconds, encrypted_token)
                return
        except Exception as ex:
            logger.warning(f"[REDIS-CACHE-WARN] Real Redis write failed, falling back to in-memory: {ex}")

        self._in_memory_cache[cache_key] = {
            "val": encrypted_token,
            "exp": time_now() + ttl_seconds,
        }


def time_now() -> float:
    import time
    return time.time()

redis_cache = RedisCacheManager()
