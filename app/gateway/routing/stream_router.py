"""
SSE Real-Time Stream HTTP Router — Module 5 EKAP
================================================
Streams pipeline execution progress via Server-Sent Events (SSE).

Real integration (2026-08-22): this previously called the disconnected
Module 4 `knowledge_retrieval_client` directly — completely bypassing
RBAC/ABAC redaction (that pipeline never applies it at all), so a
restricted-content query streamed back byte-for-byte the same content to
every role. It now goes through `ConversationService.process_turn()` (the
same live pipeline `/api/v1/search` uses) via conversation_adapter, so the
streamed progress counts (evidence retrieved, facts synthesized) reflect
the real, already-redacted result — never the raw pre-redaction context.
Also now enforces the same tenant-spoofing guard and live rate limiter as
/api/v1/search, which this endpoint had neither of before.
"""
import time
from typing import Optional
from fastapi import APIRouter, Header, Response
from fastapi.responses import StreamingResponse
from app.gateway.domain.request import ContextQueryRequest
from app.gateway.authentication.auth_handler import auth_handler
from app.gateway.adapters.conversation_adapter import process_turn_result_to_knowledge_context
from app.gateway.streaming.sse_streamer import sse_streamer
from app.gateway.audit.audit_logger import audit_logger, platform_analytics
from app.gateway.common.correlation import get_correlation_id
from app.gateway.common.exceptions import GatewayException, RateLimitException, AuthorizationException
from app.gateway.errors.problem_details import create_problem_response
from app.security.rate_limiter import rate_limiter

stream_router = APIRouter(prefix="/api/v1", tags=["Stream"])


@stream_router.post("/stream")
async def stream_context(
    req: ContextQueryRequest,
    response: Response,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    corr_id = get_correlation_id()
    t0 = time.time()

    try:
        identity = await auth_handler.authenticate(api_key=x_api_key, bearer_token=authorization)
        auth_method = "api_key" if x_api_key else "jwt"

        if req.tenant_id and str(req.tenant_id) != str(identity.tenant_id):
            raise AuthorizationException("Your credentials aren't authorized for this tenant.")

        is_allowed, remaining, limit, _is_fallback = await rate_limiter.check_rate_limit(identity.tenant_id)
        if not is_allowed:
            raise RateLimitException(f"Tenant '{identity.tenant_id}' exceeded limit of {limit} requests per minute.")
        # Real gap found via live production-readiness audit 2026-08-31: this
        # captured remaining/limit from the real limiter but never surfaced
        # them as headers — same class of gap already fixed for /stream's
        # Module 6A counterpart (see rate-limiter-tenant-isolation-bug memory).
        # A StreamingResponse is built separately below, so these must be set
        # on the shared `response` object AND copied onto the streaming one.
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
    except GatewayException as ge:
        return create_problem_response(ge, "/api/v1/stream", corr_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    # Real bug found via the same audit: this constructed a brand-new
    # ConversationService() per request instead of reusing the real shared
    # singleton every other live path (chat_router, query_scheduler after its
    # own 2026-08-24 fix) uses — a disconnected duplicate instance with its
    # own cold cache, the exact anti-pattern flagged elsewhere this
    # engagement. Reuse the real shared instance instead.
    from app.conversation.container import ConversationContainer

    caller_role = identity.roles[0].lower() if identity.roles else "member"
    turn_result = await ConversationContainer.get_conversation_service().process_turn(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        session_id=None,
        user_query=req.query,
        caller_role=caller_role,
    )
    ctx = process_turn_result_to_knowledge_context(turn_result, req.query)

    latency_ms = (time.time() - t0) * 1000.0
    await audit_logger.log_request(
        tenant_id=identity.tenant_id, user_id=identity.user_id, role=caller_role, auth_method=auth_method,
        endpoint="/api/v1/stream", query=req.query, result_count=len(ctx.retrieved_chunks), confidence=ctx.confidence.overall,
        cost_units=1, latency_ms=latency_ms, correlation_id=corr_id,
    )
    platform_analytics.record_request(latency_ms)

    return StreamingResponse(
        sse_streamer.stream_pipeline_progress(req.query, ctx),
        media_type="text/event-stream",
        headers=dict(response.headers),
    )
