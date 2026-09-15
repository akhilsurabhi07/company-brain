"""
Async Jobs HTTP Router — Module 5 EKAP
=======================================
Submits long-running background queries and polls their status.

Real integration (2026-08-22): this router did not exist before — job_manager
was wired into the DI container and exercised only by tests calling it
in-process, with no real, mounted HTTP surface, real auth, or ownership
check at all. It now mirrors the same real security posture as
/api/v1/search: real JWT/API-key auth, the same body-tenant-id spoofing
guard, the same live rate limiter, and a real per-job ownership check on
GET so tenant A can never poll a job tenant B submitted, even by guessing
or incrementing a job_id (job IDs are short and sequential-looking enough
that this is a real, not theoretical, attack surface).
"""
import time
from typing import Optional
from fastapi import APIRouter, Header, Response
from app.gateway.domain.request import JobRequest
from app.gateway.authentication.auth_handler import auth_handler
from app.gateway.jobs.job_manager import job_manager
from app.gateway.audit.audit_logger import audit_logger, platform_analytics
from app.gateway.common.correlation import get_correlation_id
from app.gateway.common.exceptions import GatewayException, RateLimitException, AuthorizationException, NotFoundException
from app.gateway.errors.problem_details import create_problem_response
from app.security.rate_limiter import rate_limiter

jobs_router = APIRouter(prefix="/api/v1", tags=["Jobs"])


async def _authenticate_and_rate_limit(x_api_key: Optional[str], authorization: Optional[str], response: Response):
    identity = await auth_handler.authenticate(api_key=x_api_key, bearer_token=authorization)
    auth_method = "api_key" if x_api_key else "jwt"
    is_allowed, remaining, limit, _is_fallback = await rate_limiter.check_rate_limit(identity.tenant_id)
    if not is_allowed:
        raise RateLimitException(f"Tenant '{identity.tenant_id}' exceeded limit of {limit} requests per minute.")
    # Real gap found via live production-readiness audit 2026-08-31: remaining/
    # limit were computed but never surfaced as response headers on either
    # endpoint sharing this helper.
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return identity, auth_method


@jobs_router.post("/jobs")
async def submit_job(
    req: JobRequest,
    response: Response,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    corr_id = get_correlation_id()
    t0 = time.time()
    try:
        identity, auth_method = await _authenticate_and_rate_limit(x_api_key, authorization, response)

        if req.tenant_id and str(req.tenant_id) != str(identity.tenant_id):
            raise AuthorizationException("Your credentials aren't authorized for this tenant.")

        caller_role = identity.roles[0].lower() if identity.roles else "member"
        job = await job_manager.submit_job(
            tenant_id=identity.tenant_id,
            query=req.query,
            user_id=identity.user_id,
            caller_role=caller_role,
            webhook_url=req.webhook_url,
        )

        latency_ms = (time.time() - t0) * 1000.0
        await audit_logger.log_request(
            tenant_id=identity.tenant_id, user_id=identity.user_id, role=caller_role, auth_method=auth_method,
            endpoint="/api/v1/jobs", query=req.query, result_count=0, confidence=0.0, cost_units=1,
            latency_ms=latency_ms, correlation_id=corr_id,
        )
        platform_analytics.record_request(latency_ms)

        return job.model_dump()
    except GatewayException as ge:
        return create_problem_response(ge, "/api/v1/jobs", corr_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


@jobs_router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    response: Response,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    corr_id = get_correlation_id()
    try:
        identity, _auth_method = await _authenticate_and_rate_limit(x_api_key, authorization, response)

        job = job_manager.get_job(job_id)
        # A nonexistent job and someone else's tenant's job must return the
        # identical 404 — a 403 here would confirm to an attacker that a
        # job_id they don't own actually exists, leaking existence across
        # tenants even though the content stays hidden.
        if job is None or str(job.tenant_id) != str(identity.tenant_id):
            raise NotFoundException("No job found with that ID.")

        return job.model_dump()
    except GatewayException as ge:
        return create_problem_response(ge, f"/api/v1/jobs/{job_id}", corr_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
