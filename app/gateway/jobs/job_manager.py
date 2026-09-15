"""
Async Job Manager & Webhook Delivery Engine — Module 5 EKAP
===========================================================
Manages long-running background graph queries and delivers POST webhooks on completion.

Real integration (2026-08-22): background jobs used to call the separate,
disconnected Module 4 `knowledge_retrieval_client` directly — no RBAC/ABAC
redaction at all, since that pipeline never applies it. A tenant's own admin
and a tenant's own lowest-privilege member would have gotten back byte-for-
byte the same unredacted content. Jobs now go through
`ConversationService.process_turn()` (via conversation_adapter), the same
live, tested pipeline `/api/v1/search` uses, so `caller_role` genuinely
gates what a completed job's result contains. `user_id` is now tracked per
job so a completed job can be ownership-checked before being handed back
(see app/gateway/routing/jobs_router.py) — a job submitted by tenant A must
never be readable by tenant B just by guessing/incrementing a job_id.
"""
import uuid
import time
import asyncio
from typing import Dict, Optional
from app.gateway.domain.jobs import JobStatus, WebhookPayload
from app.gateway.adapters.conversation_adapter import process_turn_result_to_knowledge_context


class JobManager:
    """Manages asynchronous long-running retrieval jobs."""

    def __init__(self):
        self._jobs: Dict[str, JobStatus] = {}
        self._job_owners: Dict[str, str] = {}  # job_id -> user_id (real, for ownership checks)

    async def submit_job(
        self,
        tenant_id: str,
        query: str,
        user_id: str = "unknown_user",
        caller_role: str = "member",
        webhook_url: Optional[str] = None,
    ) -> JobStatus:
        job_id = f"job_{uuid.uuid4().hex[:8]}"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status = JobStatus(
            job_id=job_id,
            tenant_id=tenant_id,
            status="PENDING",
            query=query,
            webhook_url=webhook_url,
            created_at=now
        )
        self._jobs[job_id] = status
        self._job_owners[job_id] = user_id

        # Trigger background processing task
        asyncio.create_task(self._process_job(job_id, tenant_id, query, user_id, caller_role, webhook_url))
        return status

    def get_job(self, job_id: str) -> Optional[JobStatus]:
        return self._jobs.get(job_id)

    def get_job_owner(self, job_id: str) -> Optional[str]:
        return self._job_owners.get(job_id)

    async def _process_job(
        self, job_id: str, tenant_id: str, query: str, user_id: str, caller_role: str, webhook_url: Optional[str]
    ):
        if job_id in self._jobs:
            self._jobs[job_id].status = "RUNNING"

        # Lazy import: avoids a hard import-time dependency cycle between
        # app.gateway and app.conversation for callers that never submit a job.
        # Real gap found via live production-readiness audit 2026-08-31: this
        # constructed a brand-new ConversationService() per background job
        # instead of reusing the real shared singleton — same anti-pattern
        # fixed the same audit in stream_router.py and search_service.py.
        from app.conversation.container import ConversationContainer

        try:
            turn_result = await ConversationContainer.get_conversation_service().process_turn(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=None,
                user_query=query,
                caller_role=caller_role,
            )
            ctx = process_turn_result_to_knowledge_context(turn_result, query)

            if job_id in self._jobs:
                self._jobs[job_id].status = "COMPLETED"
                self._jobs[job_id].result = ctx.model_dump()
                self._jobs[job_id].completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        except Exception as ex:
            if job_id in self._jobs:
                self._jobs[job_id].status = "FAILED"
                self._jobs[job_id].result = {"error": str(ex)}
                self._jobs[job_id].completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


job_manager = JobManager()
