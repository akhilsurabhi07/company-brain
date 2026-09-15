"""
Search Gateway HTTP Router — Module 5 EKAP
===========================================
Primary search endpoint supporting JSON, Markdown, Agent Schema, and Dashboard responses.

Real integration (2026-08-22): now also enforces the real, live, tier-based
Redis rate limiter (app/security/rate_limiter.py) — the same one every other
tenant-facing endpoint uses — rather than leaving Gateway requests
unthrottled (there was no rate limiting here at all before; the Gateway's
own separate in-memory limiter, app/gateway/infrastructure/tenant_rate_limiter.py,
was never wired in and would have duplicated it anyway).
"""
import time
from typing import Optional
from fastapi import APIRouter, Header, Response
from app.gateway.domain.request import SearchRequest
from app.gateway.domain.response import APIResponse
from app.gateway.authentication.auth_handler import auth_handler
from app.gateway.services.search_service import search_service
from app.gateway.common.correlation import get_correlation_id
from app.gateway.common.exceptions import GatewayException, RateLimitException, AuthorizationException
from app.gateway.errors.problem_details import create_problem_response
from app.security.rate_limiter import rate_limiter

search_router = APIRouter(prefix="/api/v1", tags=["Search"])

@search_router.post("/search")
async def post_search(
    req: SearchRequest,
    response: Response,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    corr_id = get_correlation_id()
    t0 = time.time()

    try:
        identity = await auth_handler.authenticate(api_key=x_api_key, bearer_token=authorization)
        auth_method = "api_key" if x_api_key else "jwt"

        # A caller-supplied tenant_id in the request body must never override
        # the real, credential-derived tenant — same real-world exploit this
        # closes as app.security.auth_dependency.verify_tenant_matches_token:
        # a valid token/key for Tenant A must not read Tenant B's data just by
        # changing a request field.
        if req.tenant_id and str(req.tenant_id) != str(identity.tenant_id):
            raise AuthorizationException("Your credentials aren't authorized for this tenant.")

        is_allowed, remaining, limit, _is_fallback = await rate_limiter.check_rate_limit(identity.tenant_id)
        if not is_allowed:
            raise RateLimitException(
                f"Tenant '{identity.tenant_id}' exceeded limit of {limit} requests per minute."
            )
        # Real gap found via live production-readiness audit 2026-08-31: `limit`
        # and `remaining` were captured from the real limiter but never
        # surfaced as response headers — a legitimate API consumer had no way
        # to see how close they were to the limit short of getting 429'd.
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        result = await search_service.execute_search(req, identity, corr_id, auth_method=auth_method)

        latency_ms = (time.time() - t0) * 1000.0

        if isinstance(result, str):  # Markdown
            return APIResponse(
                correlation_id=corr_id,
                tenant_id=identity.tenant_id,
                format=req.format,
                data={"markdown": result},
                execution_time_ms=round(latency_ms, 2)
            )

        return APIResponse(
            correlation_id=corr_id,
            tenant_id=identity.tenant_id,
            format=req.format,
            data=result,
            execution_time_ms=round(latency_ms, 2)
        )
    except GatewayException as ge:
        return create_problem_response(ge, "/api/v1/search", corr_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
