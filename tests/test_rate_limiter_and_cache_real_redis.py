"""
Real Redis verification — 2026-08-24.

Redis was confirmed unreachable throughout this whole engagement (see
env-file-lost-2026-08-19 memory: never restored). That meant
verify_tenant_rate_limit — the dependency on the real live chat endpoint
(/api/v6a/chat/turn) and Gateway's /api/v1/search — was silently failing
OPEN: every request was allowed regardless of volume, and conversation
response caching silently no-op'd. Memurai (a real Redis-compatible Windows
server) was installed and is now running. These tests prove the real
behavior actually changed, not just that Redis responds to PING.
"""
import time
import uuid
import pytest
from app.security.rate_limiter import rate_limiter, TIER_LIMITS


@pytest.mark.asyncio
async def test_rate_limiter_is_no_longer_failing_open():
    """The core proof: with Redis genuinely reachable, a real request must
    NOT be reported as a fallback/fail-open decision."""
    tenant_id = f"ratelimit-realredis-{uuid.uuid4()}"
    is_allowed, remaining, limit, is_fallback = await rate_limiter.check_rate_limit(tenant_id, "default")
    assert is_fallback is False, (
        "Redis is confirmed running — a real check must not report a fail-open fallback decision"
    )
    assert is_allowed is True
    assert limit == TIER_LIMITS["default"]


@pytest.mark.asyncio
async def test_rate_limiter_actually_blocks_once_the_real_limit_is_exceeded():
    """The real, concrete proof rate limiting is genuinely enforced now:
    hammer one tenant past its real per-minute limit and confirm the
    limiter actually says no — this could never have passed while Redis
    was unreachable (every single call would have come back allowed)."""
    tenant_id = f"ratelimit-exceed-{uuid.uuid4()}"
    tier = "standard"
    limit = TIER_LIMITS[tier]

    results = []
    for _ in range(limit + 5):
        is_allowed, remaining, lim, is_fallback = await rate_limiter.check_rate_limit(tenant_id, tier)
        results.append((is_allowed, is_fallback))

    assert all(fb is False for _, fb in results), "no call in this run should be a fail-open fallback"
    allowed_count = sum(1 for a, _ in results if a)
    blocked_count = sum(1 for a, _ in results if not a)
    assert blocked_count > 0, (
        f"expected real enforcement to block requests past the {tier} tier's {limit}/min limit, "
        f"but all {len(results)} requests were allowed"
    )
    assert allowed_count <= limit, f"real limiter allowed {allowed_count} requests, real limit is {limit}"


@pytest.mark.asyncio
async def test_rate_limiter_windows_are_genuinely_per_tenant():
    """Two different tenants must not share a rate-limit bucket — a real
    per-tenant isolation check, not just 'the limiter works at all'."""
    tenant_a = f"ratelimit-iso-a-{uuid.uuid4()}"
    tenant_b = f"ratelimit-iso-b-{uuid.uuid4()}"
    limit = TIER_LIMITS["default"]

    for _ in range(limit):
        await rate_limiter.check_rate_limit(tenant_a, "default")

    is_allowed_a, _, _, _ = await rate_limiter.check_rate_limit(tenant_a, "default")
    is_allowed_b, _, _, _ = await rate_limiter.check_rate_limit(tenant_b, "default")

    assert is_allowed_a is False, "tenant A should now be over its own real limit"
    assert is_allowed_b is True, "tenant B's real bucket must be completely unaffected by tenant A's usage"


@pytest.mark.asyncio
async def test_verify_tenant_rate_limit_uses_the_real_jwt_tenant_not_a_shared_default():
    """The critical proof for the second, more serious bug found the same
    session: verify_tenant_rate_limit used to read tenant_id only from an
    X-Tenant-ID header or request.state.tenant_id — neither of which any
    real caller anywhere in the codebase ever sets — so every real request,
    from every real tenant, fell through to one hardcoded "default_tenant"
    bucket. Real consequence: one tenant's usage could 429-reject every
    other tenant sharing the same global 30/min ceiling. Calls the real
    dependency function directly (not through a full HTTP round-trip, which
    would need real, slow LLM calls to exhaust a bucket) with two different
    real JWT-shaped tokens and proves they land in two genuinely separate
    buckets."""
    from starlette.requests import Request
    from fastapi import Response
    from app.security.rate_limiter import verify_tenant_rate_limit, TIER_LIMITS

    def _fake_request():
        scope = {"type": "http", "headers": [], "method": "POST", "path": "/api/v6a/chat/turn"}
        return Request(scope)

    tenant_a = f"jwt-tenant-a-{uuid.uuid4()}"
    tenant_b = f"jwt-tenant-b-{uuid.uuid4()}"
    limit = TIER_LIMITS["default"]

    # Exhaust tenant A's real bucket via the real dependency function.
    for _ in range(limit):
        await verify_tenant_rate_limit(_fake_request(), Response(), token={"tenant_id": tenant_a})

    # Tenant A must now be genuinely over their own limit...
    with pytest.raises(Exception) as exc_info:
        await verify_tenant_rate_limit(_fake_request(), Response(), token={"tenant_id": tenant_a})
    assert "429" in str(exc_info.value) or getattr(exc_info.value, "status_code", None) == 429

    # ...but tenant B, a completely different real JWT tenant_id, must be
    # totally unaffected — this is the exact scenario that was broken.
    try:
        await verify_tenant_rate_limit(_fake_request(), Response(), token={"tenant_id": tenant_b})
    except Exception as ex:
        pytest.fail(f"tenant B must not be rate-limited by tenant A's usage — the real bug this fix addresses: {ex}")


@pytest.mark.asyncio
async def test_conversation_cache_now_actually_persists_between_calls():
    """Real proof the conversation cache (Redis-backed, previously silently
    disabled) genuinely stores and returns a value now, not just that its
    Redis client connects."""
    from app.conversation.cache.conversation_cache import ConversationCache
    from app.conversation.domain.response_payload import MultimodalResponsePayload

    cache = ConversationCache()
    cache_key = f"cache-real-test-{uuid.uuid4()}"
    payload = MultimodalResponsePayload(text_content="real cached answer, not a stub")

    await cache.set(cache_key, payload)
    result = await cache.get(cache_key)

    assert result is not None, "a real Redis-backed cache write must be readable back — it was silently no-op'ing before"
    assert result.text_content == "real cached answer, not a stub"
