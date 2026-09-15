import time
import logging
from typing import Dict, Tuple, Optional
from fastapi import Request, Response, Depends, HTTPException, status
from app.config import settings
from app.security.auth_dependency import require_authenticated_tenant as _require_authenticated_tenant_dep

logger = logging.getLogger("company_brain.rate_limiter")

# Per-tenant tier default request limits per minute
TIER_LIMITS: Dict[str, int] = {
    "enterprise": 100,
    "standard": 20,
    "default": 30,
}

class RedisRateLimiter:
    """
    Enterprise Redis-backed sliding window rate limiter with Fail-Open resilience.
    """

    def __init__(self, redis_client=None):
        self.redis_client = redis_client

    async def _get_redis(self):
        if self.redis_client is not None:
            return self.redis_client
        try:
            import redis.asyncio as aioredis
            # Real bug found via live Redis verification 2026-08-24: measured
            # directly against the real Redis instance now running — the very
            # first command on a fresh connection (connection establishment +
            # handshake, redis-py's async client connects lazily on first use)
            # genuinely takes ~2.0-2.1s here; every call after that on the same
            # client is ~0.000s. The old 1.5s timeout was tighter than that
            # real, reproducible one-time cost, so the real first rate-limit
            # check of this process's lifetime always timed out and fell back
            # to fail-open — meaning rate limiting silently never engaged even
            # with Redis genuinely reachable. 4s gives real headroom above the
            # measured cost without weakening the actual fail-open-on-real-
            # outage behavior below (a genuine sustained outage still fails
            # open, just no longer a merely-slow first connection).
            self.redis_client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=4.0,
                socket_connect_timeout=4.0
            )
            return self.redis_client
        except Exception as ex:
            logger.warning(f"[RATE-LIMITER-WARN] Failed to initialize Redis connection: {ex}")
            return None

    async def check_rate_limit(self, tenant_id: str, tier: str = "default") -> Tuple[bool, int, int, bool]:
        """
        Check per-tenant sliding window rate limit.
        
        Returns:
            (is_allowed: bool, remaining: int, limit: int, is_fallback: bool)
        """
        limit = TIER_LIMITS.get(tier.lower(), TIER_LIMITS["default"])
        window_seconds = 60
        now = time.time()
        key = f"rate_limit:{tenant_id}:{int(now // window_seconds)}"

        try:
            r = await self._get_redis()
            if r is None:
                # Fail-open if Redis client unavailable
                return True, limit, limit, True

            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds + 5)
            results = await pipe.execute()
            
            current_count = results[0]
            remaining = max(0, limit - current_count)
            is_allowed = current_count <= limit

            return is_allowed, remaining, limit, False

        except Exception as ex:
            logger.warning(f"[RATE-LIMITER-FAIL-OPEN] Redis connection error during check for tenant '{tenant_id}': {ex}. Failing OPEN gracefully.")
            # Fail OPEN on Redis outage to prevent taking down product
            return True, limit, limit, True

rate_limiter = RedisRateLimiter()

async def verify_tenant_rate_limit(
    request: Request, response: Response,
    token: dict = Depends(_require_authenticated_tenant_dep),
):
    """
    FastAPI dependency to enforce tenant-scoped rate limiting with Fail-Open headers.

    Real bug found via live production-issue review 2026-08-24: tenant_id was
    read only from an X-Tenant-ID header or request.state.tenant_id — neither
    of which any real caller in this whole codebase ever sets (grepped every
    frontend and backend file). Every real request, from every real tenant,
    fell through to the hardcoded "default_tenant" fallback — meaning this
    "tenant-scoped" limiter was actually one single global bucket shared by
    the entire live product. One tenant's real usage (or just several
    tenants' combined normal usage) could exhaust the shared 30/min ceiling
    and start 429-rejecting every other tenant's requests, including ones
    who made none of the offending calls themselves. Fixed to take the real
    JWT payload from require_authenticated_tenant (the same auth dependency
    every endpoint that uses this already requires) as its real, primary
    source of tenant_id — the header/state path is kept only as a fallback
    for a hypothetical future unauthenticated caller, not the real path any
    current endpoint takes.
    """
    real_tenant_id = (token or {}).get("tenant_id")
    tenant_id = real_tenant_id or request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", "default_tenant")
    tenant_tier = request.headers.get("X-Tenant-Tier", "default")

    is_allowed, remaining, limit, is_fallback = await rate_limiter.check_rate_limit(tenant_id, tenant_tier)

    # Attach standard RateLimit headers to response
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)

    if is_fallback:
        response.headers["X-RateLimit-Fallback"] = "true"
        logger.info(f"[RATE-LIMITER] Applied Fail-Open fallback for tenant '{tenant_id}'")

    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit exceeded",
                "message": f"Tenant '{tenant_id}' exceeded limit of {limit} requests per minute.",
                "tenant_id": tenant_id,
                "retry_after_seconds": 60
            },
            headers={
                "Retry-After": "60",
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0"
            }
        )
