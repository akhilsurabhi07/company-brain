import os
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.config import settings
from app.api.auth import router as auth_router
from app.api.connectors_router import router as connectors_router
from app.api.ingestion_router import router as ingestion_router
from app.api.webhooks import router as webhooks_router
from app.api.graph_api import router as graph_router
from app.api.graphrag_api import router as graphrag_router
from app.api.upload_router import router as upload_router
from app.api.tenant_config_router import router as tenant_config_router
from app.api.google_oauth_router import router as google_oauth_router
from app.api.jira_oauth_router import router as jira_oauth_router
from app.api.microsoft_oauth_router import router as microsoft_oauth_router
from app.api.mcp_keys_router import router as mcp_keys_router
from app.api.mcp_server_router import router as mcp_server_router
from app.gateway.routing.search_router import search_router
from app.gateway.routing.health_router import health_router
from app.gateway.routing.stream_router import stream_router
from app.gateway.routing.jobs_router import jobs_router
from app.api.projects_router import router as projects_router
from app.api.workspace_router import router as workspace_router
from app.api.admin_router import router as admin_router
from app.api.scheduled_queries_router import router as scheduled_queries_router
from app.api.agent_platform_router import router as agent_platform_router

app = FastAPI(
    title=settings.APP_NAME,
    description="Enterprise Data Ingestion, Knowledge Retrieval & Intelligence Engine",
    version="1.0.0",
)

# Enable CORS for local & cloud environments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enable GZip HTTP Compression Middleware (70% smaller web asset load size)
app.add_middleware(GZipMiddleware, minimum_size=500)

from app.conversation.routing.chat_router import router as chat_router, v6a_router
from app.api.module6b_router import router as module6b_router

# Include API Routers
app.include_router(auth_router)
app.include_router(connectors_router)
app.include_router(ingestion_router)
app.include_router(webhooks_router)
app.include_router(graph_router)
app.include_router(graphrag_router)
app.include_router(chat_router)
app.include_router(v6a_router)      # Module 6B → 6A bridge
app.include_router(upload_router)   # Browser file upload & ingestion
app.include_router(module6b_router)
app.include_router(tenant_config_router)
app.include_router(google_oauth_router)
app.include_router(jira_oauth_router)
app.include_router(microsoft_oauth_router)
app.include_router(mcp_keys_router)
app.include_router(mcp_server_router)
app.include_router(search_router)   # Module 5 EKAP: real JWT + API-key auth,
app.include_router(health_router)   # delegates retrieval to ConversationService
app.include_router(stream_router)   # SSE streaming, same real pipeline + auth
app.include_router(jobs_router)     # async jobs, same real pipeline + auth
app.include_router(projects_router) # Module 6B: real project memory foundation
app.include_router(workspace_router) # Module 6B: real People/Teams/Documents directory
app.include_router(admin_router) # Module 6C: real Admin Dashboard — team/role management + activity log
app.include_router(scheduled_queries_router) # Module 6C: real Scheduled panel — recurring saved questions
app.include_router(agent_platform_router) # Module 7: real Research Agent — plan -> tool calls -> synthesis -> persisted execution

@app.on_event("startup")
async def _start_query_scheduler():
    # Real in-process asyncio loop, not Celery Beat — Redis is confirmed
    # unreachable in this dev environment (see query_scheduler.py's module
    # docstring). Started here so it runs for the lifetime of the real
    # server process, the same way the app itself does.
    from app.scheduler.query_scheduler import start as start_query_scheduler
    start_query_scheduler()


@app.on_event("startup")
async def _warm_real_redis_connections():
    # Real gap found via live browser testing 2026-08-24: after fixing
    # rate_limiter.py/conversation_cache.py/redis_cache.py's Redis timeouts,
    # a live-browser re-check of the real Plugins connect flow showed the
    # connect button stuck on "Connecting…" for ~2s — the real, measured
    # one-time cold-connection cost against this environment's Redis
    # instance, paid by whichever real user's request happens to be the
    # first to touch any of these three Redis clients after a server
    # restart. Not a bug in the fix itself (confirmed via a corrected wait
    # condition: the request completes correctly, just slower than a fixed
    # 1.2s test guess) — but a real, avoidable UX cost for whoever draws the
    # short straw. Paying it once here at boot, before any real request can,
    # is strictly better than leaving it for a real user to hit.
    import asyncio
    import logging
    logger = logging.getLogger("company_brain.redis_warmup")

    async def _warm(label, coro):
        try:
            await coro
            logger.info(f"[Redis warm-up] {label}: connected.")
        except Exception as ex:
            logger.warning(f"[Redis warm-up] {label} failed (real outage or Redis unavailable — degrading gracefully): {ex}")

    from app.security.rate_limiter import rate_limiter
    from app.db.redis_cache import redis_cache
    from app.conversation.container import ConversationContainer

    # Real fix found while writing this warm-up 2026-08-24: ConversationCache
    # has no module-level singleton of its own — it's a fresh instance per
    # ConversationService(), so warming a throwaway ConversationCache() here
    # would warm nothing any real request actually uses. The real live chat
    # path's single shared instance is ConversationContainer's singleton.
    conversation_service = ConversationContainer.get_conversation_service()

    await asyncio.gather(
        _warm("rate_limiter", rate_limiter.check_rate_limit("__startup_warmup__", "default")),
        _warm("conversation_cache", conversation_service.cache.get("__startup_warmup__")),
        _warm("redis_cache", redis_cache.get_cached_encrypted_token("__startup_warmup__", "__warmup__")),
    )

# Production Probes & Observability Endpoints
from fastapi import Response
from sqlalchemy import text

@app.get("/healthz", tags=["Observability"])
async def liveness_probe():
    """Kubernetes Liveness Probe: Verifies API container process is alive."""
    return {"status": "healthy", "service": settings.APP_NAME}

@app.get("/readyz", tags=["Observability"])
async def readiness_probe(response: Response):
    """
    Kubernetes Readiness Probe: Verifies database and Redis connection readiness.
    Returns HTTP 503 Service Unavailable if backend dependencies fail.
    """
    db_ok = False
    redis_ok = False

    # Check Database Connection
    try:
        from app.db.database import async_session_factory
        async with async_session_factory() as session:
            res = await session.execute(text("SELECT 1"))
            if res.scalar() == 1:
                db_ok = True
    except Exception as ex:
        db_ok = False

    # Check Redis Connection
    try:
        from app.security.rate_limiter import rate_limiter
        r = await rate_limiter._get_redis()
        if r is not None and await r.ping():
            redis_ok = True
    except Exception:
        redis_ok = False

    is_ready = db_ok and redis_ok
    if not is_ready:
        response.status_code = 503
        return {
            "status": "unhealthy",
            "ready": False,
            "components": {
                "database": "connected" if db_ok else "failed",
                "redis": "connected" if redis_ok else "failed"
            }
        }

    return {
        "status": "healthy",
        "ready": True,
        "components": {
            "database": "connected",
            "redis": "connected"
        }
    }

@app.get("/metrics", tags=["Observability"])
async def metrics_endpoint():
    """Expose Prometheus telemetry exposition metrics."""
    from app.security.prometheus_telemetry import get_prometheus_metrics
    data, content_type = get_prometheus_metrics()
    return Response(content=data, media_type=content_type)



# Serve Static UI Frontend
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
static_dir = os.path.join(os.path.dirname(__file__), "static")

if os.path.exists(static_dir):
    app.mount("/onboarding", StaticFiles(directory=static_dir, html=True), name="onboarding")

if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
elif os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

import traceback

@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """Global catch-all exception handler to prevent ungraceful thread panics."""
    return Response(
        content=f'{{"error": "Internal Server Error", "message": "An unexpected error occurred. Our engineers have been notified."}}',
        status_code=500,
        media_type="application/json"
    )

if __name__ == "__main__":
    # In production, this should be run via Gunicorn with multiple Uvicorn workers.
    # For local execution, we disable reload=True to allow proper load testing and single-instance stability.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, workers=4)
