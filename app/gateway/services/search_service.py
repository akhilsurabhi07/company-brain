"""
Search Service Application Layer — Module 5 EKAP
================================================
Orchestrates query normalization, real RBAC-aware retrieval, and response
format transformation.

Real integration (2026-08-22): this used to call the separate, less-mature
Module 4 `knowledge_retrieval_client` for retrieval, then apply this
module's own `policy_engine.authorize_request()` / `filter_context_for_user()`
for RBAC/ABAC — both of which duplicate and are inferior to real, already
live behavior:
  - `authorize_request()` hard-blocked entire queries containing salary/
    payroll wording for non-Admin/HR_Lead roles — a different, stricter UX
    than the live system's sentence-level redaction, and would regress the
    "leave policy" mixed-content fix already verified in ConversationService.
  - `filter_context_for_user()` did whole-chunk-drop content filtering,
    duplicating (less precisely than) the live `_redact_if_restricted()`
    sentence-level redaction already applied inside `process_turn()` itself.

Both calls are removed. Retrieval + RBAC/ABAC redaction + grounding +
citations + multi-hop graph enrichment now all come from one place:
`ConversationService.process_turn()` — the same live, fully-tested pipeline
backing `/api/v6a/chat/turn` — via `conversation_adapter`, which reshapes its
result into a `KnowledgeContext` so the existing format transformers below
need no changes.
"""
import time
from typing import Dict, Any, Union

from app.conversation.container import ConversationContainer
from app.gateway.adapters.conversation_adapter import process_turn_result_to_knowledge_context
from app.gateway.domain.request import SearchRequest
from app.gateway.domain.auth import UserIdentity
from app.gateway.normalization.query_normalizer import query_normalizer
from app.gateway.transformers.markdown_transformer import markdown_transformer
from app.gateway.transformers.agent_transformer import agent_transformer, dashboard_transformer, mobile_transformer
from app.gateway.audit.audit_logger import audit_logger, platform_analytics
from app.gateway.events.integration.event_contracts import event_bus, SearchCompletedEvent

# Real gap found via live production-readiness audit 2026-08-31: this used to
# construct its own module-level ConversationService() instance -- a real,
# separate instance from the one ConversationContainer hands every other live
# path (chat_router, and stream_router/job_manager after their own fixes the
# same audit), with its own cache/session state. Same anti-pattern already
# fixed elsewhere this engagement (query_scheduler.py, 2026-08-24) -- reuse
# the real shared singleton instead of a disconnected duplicate.
_conversation_service = ConversationContainer.get_conversation_service()


class SearchService:
    """Orchestrates search execution across EKAP subsystems."""

    async def execute_search(
        self, req: SearchRequest, identity: UserIdentity, correlation_id: str, auth_method: str = "jwt"
    ) -> Union[Dict[str, Any], str]:
        t0 = time.time()

        # 1. Normalize query and resolve aliases (real, harmless: whitespace
        #    cleanup + known-entity alias hints; does not affect RBAC/security).
        normalized_query, _entity_hints = query_normalizer.normalize(req.query)

        # 2. Retrieve via the real, live conversation pipeline. caller_role
        #    drives ConversationService's own sentence-level RBAC/ABAC
        #    redaction — the single real source of truth for what this
        #    identity is allowed to see, never re-derived here.
        caller_role = identity.roles[0].lower() if identity.roles else "member"
        turn_result = await _conversation_service.process_turn(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            session_id=None,
            user_query=normalized_query,
            caller_role=caller_role,
        )

        context = process_turn_result_to_knowledge_context(turn_result, normalized_query)

        # 3. Transform response based on client format requirement
        if req.format == "markdown":
            formatted_output = markdown_transformer.transform(context)
        elif req.format == "agent_schema":
            formatted_output = agent_transformer.transform(context)
        elif req.format == "dashboard":
            formatted_output = dashboard_transformer.transform(context)
        elif req.format == "mobile":
            formatted_output = mobile_transformer.transform(context)
        else:
            formatted_output = context.model_dump()

        latency_ms = (time.time() - t0) * 1000.0

        # 4. Audit & Analytics Logging — real, persistent (gateway_audit_log).
        await audit_logger.log_request(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            role=caller_role,
            auth_method=auth_method,
            endpoint="/api/v1/search",
            query=normalized_query,
            result_count=len(context.retrieved_chunks),
            confidence=context.confidence.overall,
            cost_units=1,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
        )
        platform_analytics.record_request(latency_ms)

        # 5. Post-Response Event Publishing (in-memory pub-sub; never claimed
        #    to be durable, so left as-is).
        event_bus.publish(SearchCompletedEvent(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            query=normalized_query,
            intent=context.intent,
            result_count=len(context.retrieved_chunks),
            cost_units=1,
            latency_ms=latency_ms,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ))

        return formatted_output


search_service = SearchService()
