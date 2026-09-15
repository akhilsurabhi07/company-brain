"""
Native Python SDK Client — Module 5 EKAP
========================================
CompanyBrainClient providing clean programmatic access to Company Brain EKAP.

Real integration (2026-08-22): this previously built a `UserIdentity`
directly from the constructor's raw `tenant_id` string with zero credential
verification — any caller could hand it an arbitrary `tenant_id` and get
back a real identity for it, no real auth performed at all. It now
authenticates through the same real `auth_handler` every HTTP route uses
(JWT or API key), so `tenant_id`/role always come from a verified
credential rather than a caller-supplied constructor argument. This client
is not currently wired into any exposed endpoint, but it is a real,
importable in-process bypass path if left unauthenticated, so it gets the
same fix regardless.
"""
from typing import Dict, Any, Optional
from app.gateway.domain.request import SearchRequest, JobRequest
from app.gateway.authentication.auth_handler import auth_handler
from app.gateway.services.search_service import search_service
from app.gateway.jobs.job_manager import job_manager


class CompanyBrainClient:
    """Async Python SDK client for Company Brain."""

    def __init__(self, api_key: Optional[str] = None, bearer_token: Optional[str] = None):
        self.api_key = api_key
        self.bearer_token = bearer_token

    async def _identity(self):
        return await auth_handler.authenticate(api_key=self.api_key, bearer_token=self.bearer_token)

    async def search(self, query: str, format: str = "json", max_results: int = 10) -> Dict[str, Any]:
        """Performs search and returns formatted result."""
        identity = await self._identity()
        auth_method = "api_key" if self.api_key else "jwt"
        req = SearchRequest(query=query, format=format, max_results=max_results)
        res = await search_service.execute_search(req, identity, "sdk_corr_id", auth_method=auth_method)
        if isinstance(res, str):
            return {"markdown": res}
        return res

    async def submit_async_job(self, query: str, webhook_url: Optional[str] = None):
        """Submits asynchronous long-running job."""
        identity = await self._identity()
        caller_role = identity.roles[0].lower() if identity.roles else "member"
        return await job_manager.submit_job(
            tenant_id=identity.tenant_id, query=query, user_id=identity.user_id,
            caller_role=caller_role, webhook_url=webhook_url,
        )
