"""
Real Redis-backed token cache — 2026-08-24.

Found while reviewing this engagement's remaining Redis gaps:
RedisCacheManager's name, docstring, and "SECURITY GUARANTEE" comment all
claimed real Redis-backed caching, but it was a plain in-process dict with
no Redis connection at all — write-only (nothing in the live app ever read
from it) and a genuine unbounded memory leak (expired entries were only
ever skipped on read, never evicted). Fixed to use real Redis with native
TTL. These tests exercise the real class AND the real live connect_app
endpoint end to end, not just the cache in isolation.
"""
import uuid
import httpx
import pytest
import redis.asyncio as aioredis
from app.main import app
from app.config import settings
from app.db.redis_cache import redis_cache
from tests.conftest import auth_headers_for


@pytest.mark.asyncio
async def test_cache_manager_writes_to_real_redis_not_memory():
    """Direct proof: a value written through the class is readable via a
    completely separate, independent Redis client — impossible if it were
    still an in-process dict."""
    tenant_id = str(uuid.uuid4())
    source_app = "github"
    fake_encrypted_token = f"fake-cipher-{uuid.uuid4()}"

    await redis_cache.set_cached_encrypted_token(tenant_id, source_app, fake_encrypted_token)

    independent_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=4.0)
    try:
        real_value = await independent_client.get(f"tenant:{tenant_id}:token:{source_app}")
        assert real_value == fake_encrypted_token, (
            "value must be readable from a completely independent Redis client — "
            "proves this landed in real Redis, not process memory"
        )
        real_ttl = await independent_client.ttl(f"tenant:{tenant_id}:token:{source_app}")
        assert 0 < real_ttl <= 900, f"expected a real ~15-minute TTL, got {real_ttl}s"
    finally:
        await independent_client.delete(f"tenant:{tenant_id}:token:{source_app}")
        await independent_client.aclose()


@pytest.mark.asyncio
async def test_cache_manager_get_reads_back_what_was_set():
    tenant_id = str(uuid.uuid4())
    source_app = "slack"
    token = f"real-round-trip-{uuid.uuid4()}"

    await redis_cache.set_cached_encrypted_token(tenant_id, source_app, token)
    result = await redis_cache.get_cached_encrypted_token(tenant_id, source_app)
    assert result == token

    independent_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=4.0)
    await independent_client.delete(f"tenant:{tenant_id}:token:{source_app}")
    await independent_client.aclose()


@pytest.mark.asyncio
async def test_real_connect_endpoint_actually_populates_real_redis():
    """End-to-end, through the real live API a user actually hits — not the
    cache class called directly."""
    from sqlalchemy import text
    from app.db.database import async_session_factory

    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": "Redis Cache Endpoint Test", "domain": f"rediscache-{tenant_id[:8]}.example.com"},
        )
        await session.commit()

    headers = auth_headers_for(tenant_id)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/connectors/connect",
                json={"tenant_id": tenant_id, "source_app": "github", "action": "connect", "access_token": "ghp_real_endpoint_test"},
                headers=headers,
            )
            assert resp.status_code == 200

        independent_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=4.0)
        try:
            real_value = await independent_client.get(f"tenant:{tenant_id}:token:github")
            assert real_value is not None, (
                "the real /connectors/connect endpoint must leave a real cached entry in real Redis"
            )
        finally:
            await independent_client.delete(f"tenant:{tenant_id}:token:github")
            await independent_client.aclose()
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(text("DELETE FROM oauth_tokens WHERE tenant_id = :t"), {"t": tenant_id})
            await session.execute(text("DELETE FROM sync_statuses WHERE tenant_id = :t"), {"t": tenant_id})
            await session.commit()
        async with async_session_factory() as session:
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
            await session.commit()
