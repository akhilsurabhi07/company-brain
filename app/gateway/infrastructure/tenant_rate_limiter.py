"""
Distributed Token-Bucket Tenant Rate Limiter — Module 5 EKAP
============================================================
Enforces Requests-Per-Minute (RPM) quotas per tenant using a token bucket algorithm.
"""
import time
import asyncio
from typing import Dict

class TenantRateLimiter:
    """Token bucket rate limiter enforcing tenant quotas."""

    def __init__(self, default_capacity: int = 120, refill_rate_per_sec: float = 2.0):
        self.default_capacity = default_capacity
        self.refill_rate_per_sec = refill_rate_per_sec
        self.buckets: Dict[str, Dict[str, float]] = {}

    async def acquire(self, tenant_id: str) -> bool:
        now = time.time()
        if tenant_id not in self.buckets:
            self.buckets[tenant_id] = {
                "tokens": float(self.default_capacity),
                "last_refill": now
            }

        bucket = self.buckets[tenant_id]
        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(float(self.default_capacity), bucket["tokens"] + (elapsed * self.refill_rate_per_sec))
        bucket["last_refill"] = now

        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True
        return False

tenant_rate_limiter = TenantRateLimiter()
