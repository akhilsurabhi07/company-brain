"""Module 6A FastAPI REST API Router."""

from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from app.conversation.container import ConversationContainer
from app.conversation.domain.persona import PersonaType
from app.conversation.domain.modes import ConversationMode
from app.conversation.export.exporter import ConversationExporter
from app.conversation.streaming.sse_engine import SSEStreamingEngine
from app.conversation.interfaces.llm_provider import GenerationRequest
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token

router = APIRouter(prefix="/api/v1/chat", tags=["Module 6A Conversational Intelligence"])


class ChatTurnRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID derived from Auth JWT (Required)")
    user_id: str = Field(..., description="User ID derived from Auth JWT (Required)")
    session_id: Optional[str] = None
    user_query: str
    persona: PersonaType = PersonaType.ENGINEER
    mode: ConversationMode = ConversationMode.ASK
    knowledge_context: Any = "KnowledgeContext v1.0.0 Grounded Baseline"
    use_consensus: bool = False


class CreateSessionRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID (Required)")
    user_id: str = Field(..., description="User ID (Required)")
    title: str = "New Conversation"


class V6AChatTurnRequest(BaseModel):
    """Extended request schema used by the Module 6B EXL frontend."""
    tenant_id: str = Field(..., description="Tenant ID derived from Auth JWT (Required)")
    user_id: str = Field("user_default", description="User ID")
    session_id: Optional[str] = None
    user_query: str
    history: Optional[List[Dict[str, Any]]] = None
    persona: PersonaType = PersonaType.CTO
    # Real bug found via live testing 2026-08-21: this defaulted to
    # ConversationMode.ARCHITECTURE_REVIEW, whose prompt template hardcodes "Perform a
    # deep architecture review... Evaluate scalability, bottlenecks, and security" —
    # glued onto every single query, regardless of topic. The real frontend has no UI
    # to select a mode at all, so every real chat message sent through the live
    # product got this instruction attached. Confirmed live: a plain "what is our
    # remote work policy" question correctly detected a real conflict between two
    # documents, then went on to hallucinate a fictional "architecture review"
    # tangent the user never asked about — directly caused by this default, not
    # generic LLM non-determinism (which is what an earlier pass in this session
    # mistakenly attributed a symptom of this same bug to). ASK is the real neutral
    # mode — PromptCompiler correctly falls through to a plain, non-hijacking prompt
    # for any mode name that isn't a specialized template's key.
    mode: ConversationMode = ConversationMode.ASK
    knowledge_context: Any = "KnowledgeContext v1.0.0 Grounded Baseline"
    use_consensus: bool = False
    preferred_provider: Optional[str] = None   # hint from UI model selector
    # Opt-in per-turn retrieval diagnostics (candidate counts, latencies, rerank scores)
    # surfaced only to the frontend's "Dev Telemetry Mode" toggle — never attached
    # otherwise. Replaces the old fake "Execution Timeline" panel, which always showed
    # the same hardcoded 6-step list regardless of what actually happened.
    debug_retrieval: bool = False


v6a_router = APIRouter(prefix="/api/v6a/chat", tags=["Module 6B → 6A Bridge"])


from app.security.rate_limiter import verify_tenant_rate_limit

@v6a_router.post("/turn", dependencies=[Depends(verify_tenant_rate_limit)])
async def v6a_chat_turn(req: V6AChatTurnRequest, token=Depends(require_authenticated_tenant)):
    """
    Module 6B → 6A bridge endpoint.
    Strictly validates tenant_id from request auth context and delegates to
    Module 6A conversation service with PostgreSQL RLS enforcement.
    """
    real_tenant_id = verify_tenant_matches_token(req.tenant_id, token)
    """
    Module 6B → 6A bridge endpoint.
    Accepts the full EXL frontend request shape and delegates to the
    Module 6A conversation service.  Returns a normalised response that
    includes the provider name so the UI status bar stays accurate.
    """
    service = ConversationContainer.get_conversation_service()
    result = await service.process_turn(
        tenant_id=real_tenant_id,
        user_id=req.user_id,
        session_id=req.session_id,
        user_query=req.user_query,
        persona=req.persona,
        mode=req.mode,
        knowledge_context=req.knowledge_context,
        use_consensus=req.use_consensus,
        preferred_provider=req.preferred_provider,
        history=req.history,
        debug_retrieval=req.debug_retrieval,
        # Real security bug found via code audit 2026-09-11: this defaulted a
        # token with no "role" claim to "admin" -- the HIGHEST privilege --
        # instead of failing closed to the lowest one, unlike every other real
        # call site in this codebase. See the matching fix and full rationale
        # below in this same file for the /stream equivalent.
        caller_role=token.get("role") or "member",
    )

    # Normalise response keys so the frontend can always read
    # result.response_text and result.provider safely.
    response_text = (
        result.get("response_text")
        or result.get("response")
        or result.get("answer")
        or "Turn executed successfully."
    )
    provider = (
        result.get("provider")
        or req.preferred_provider
        or "company-brain"
    )

    # Same real fix as /stream below: surface real per-document citations
    # (from explanation.evidence_used, the actually-retrieved chunks) instead
    # of a top-level "citations" key that was never set on the real RAG path.
    _evidence_used = (result.get("explanation") or {}).get("evidence_used") or []
    citations = []
    for _e in _evidence_used:
        _t = _e.get("doc_title")
        if _t and _t not in citations:  # dedupe: multiple chunks from one doc are one real citation
            citations.append(_t)

    return {
        **result,
        "response_text": response_text,
        "provider": provider,
        "citations": citations,
        "persona": req.persona.value,
        "mode": req.mode.value,
    }


@v6a_router.post("/stream", dependencies=[Depends(verify_tenant_rate_limit)])
async def v6a_chat_stream(req: V6AChatTurnRequest, response: Response, token=Depends(require_authenticated_tenant)):
    """
    SSE Streaming endpoint — same logic as /turn but streams the response
    word-by-word so the frontend can render tokens progressively.
    Events:
      data: {"type": "token",  "content": "word "}
      data: {"type": "done",   "citations": [...], "confidence": 82, "provider": "groq"}
      data: {"type": "error",  "message": "..."}

    Real gap found via live production-issue review 2026-08-24: this is the
    real primary path the frontend actually uses (STREAM_URL in app.js —
    /turn is only a fallback when streaming itself is unavailable), and it
    had no rate limiting at all — only /turn did. Added the same dependency
    /turn already has; see verify_tenant_rate_limit's own docstring for the
    separate, more serious bug (a shared global bucket instead of real
    per-tenant ones) fixed in the same pass.

    Second real gap found immediately after, via live browser verification:
    verify_tenant_rate_limit sets real X-RateLimit-* headers on the
    `response: Response` FastAPI injects into it — but this endpoint builds
    and returns its own separate StreamingResponse(...) object below, so
    those headers were silently discarded; a live check showed them all
    coming back None despite the limiter genuinely working underneath
    (confirmed separately: a real 429 with the correct tenant_id fires in
    ~0.02s once a tenant's real limit is hit — enforcement itself was never
    affected, only the informational headers on successful responses).
    FastAPI shares the same Response object across a dependency and the
    endpoint when both declare `response: Response`, so copying its headers
    into the real StreamingResponse fixes the visibility gap too.
    """
    real_tenant_id = verify_tenant_matches_token(req.tenant_id, token)

    async def generate():
        import asyncio, json

        try:
            service = ConversationContainer.get_conversation_service()
            result = await service.process_turn(
                tenant_id=real_tenant_id,
                user_id=req.user_id,
                session_id=req.session_id,
                user_query=req.user_query,
                persona=req.persona,
                mode=req.mode,
                knowledge_context=req.knowledge_context,
                use_consensus=req.use_consensus,
                preferred_provider=req.preferred_provider,
                history=req.history,
                debug_retrieval=req.debug_retrieval,
                # Real security bug found via code audit 2026-09-11: this defaulted
                # a token with no "role" claim to "admin" -- the HIGHEST privilege
                # -- instead of failing closed to the lowest one, the opposite of
                # every other real call site in this codebase (gateway routers,
                # search_service.py, graph_api.py all correctly default to
                # "member"). A real JWT issued by this app's own signup/login
                # always carries a role, so this wasn't reachable in normal
                # operation -- but a security-relevant default must fail closed
                # regardless of whether the unsafe path is "usually" unreachable,
                # on both of the two most-used real chat endpoints in the product.
                caller_role=token.get("role") or "member",
            )

            response_text = (
                result.get("response_text")
                or result.get("response")
                or result.get("answer")
                or "I processed your request."
            )
            if isinstance(response_text, dict):
                # Real bug found via live testing 2026-08-23: falling back to
                # json.dumps(response_text) here meant that on the rare occasion
                # text_content itself was empty, the user was shown the raw
                # internal envelope ({"text_content": "", "citations": [...],
                # ...}) as if it were the chat answer — a hard failure should
                # read as an honest error, never as leaked internals.
                response_text = response_text.get("text_content") or (
                    "Something went wrong generating a response. Please try asking again."
                )

            # Real bug found live 2026-09-15: this read a top-level "citations" key
            # that conversation_service.py's real RAG-path return dict never sets
            # (citations only ever existed nested under result["response"]["citations"],
            # and even that was just a generic per-PROVIDER placeholder like
            # "Groq (model)" set by the LLM adapter -- never the real per-document
            # sources that actually grounded the answer). The result: every single
            # real chat answer sent "citations": [] to the frontend's evidence panel,
            # regardless of how well-grounded the answer actually was -- on /stream,
            # the documented real primary path the frontend uses (see this
            # function's own docstring). explanation_engine.py was already building
            # exactly the right real data for this (evidence_used: real doc_title
            # per actually-retrieved chunk) but chat_router.py was never updated to
            # consume it. Frontend's citations renderer (app.js openInspectorModal)
            # expects a flat array of title strings, not objects -- match that shape.
            _evidence_used = (result.get("explanation") or {}).get("evidence_used") or []
            citations = []
            for _e in _evidence_used:
                _t = _e.get("doc_title")
                if _t and _t not in citations:  # dedupe: multiple chunks from one doc are one real citation
                    citations.append(_t)
            confidence      = result.get("confidence_score", 0)
            provider_out    = result.get("provider") or req.preferred_provider or "company-brain"
            retrieval_debug = result.get("retrieval_debug")  # only present when req.debug_retrieval was True
            explanation     = result.get("explanation")
            # Real bug found via live testing 2026-08-21: the SSE "done" event never
            # carried the real turn_id, so the frontend generated a fake client-side
            # "msg_<timestamp>" id per message and submitted feedback (thumbs up/down)
            # against that fake id — feedback was being stored with zero relationship
            # to the real conversation turn it was actually about.
            turn_id         = result.get("turn_id")
            # Real bug found via live testing 2026-08-22: the client sends its
            # own client-generated session_id ("sess_" + Date.now()), which
            # never matches a real backend session on the very first turn of
            # a conversation — process_turn() always mints its own real
            # session_id when the client's guess isn't found (see
            # SessionManager.create_session). Without this field, the client
            # had no way to learn that real ID and kept sending its own,
            # fake one on every subsequent turn too — meaning the durable,
            # per-turn history now written to Postgres
            # (conversation_sessions/conversation_turns) never accumulated
            # more than one turn per real session row.
            real_session_id = result.get("session_id")

            # Stream word by word (~80 words/sec)
            #
            # CRITICAL real bug found via live testing 2026-08-21: this loop variable
            # was also named `token` — an innocent naming coincidence with the outer
            # function's `token=Depends(require_authenticated_tenant)` JWT parameter.
            # Because generate() (this nested closure) assigns to `token` ANYWHERE in
            # its body, Python treats `token` as local to the WHOLE closure — making
            # line ~154's earlier, legitimate read of the real JWT token
            # (`token.get("role", "admin")`) raise "cannot access local variable
            # 'token'" before this loop ever ran. This is the same Python scoping
            # gotcha documented elsewhere in this codebase, just from an unrelated
            # naming collision this time. Confirmed live: EVERY real /stream call —
            # the frontend's primary chat path — was returning an "error" SSE event
            # with exactly this message instead of a real answer.
            words = response_text.split(" ")
            for i, word in enumerate(words):
                word_token = word + ("" if i == len(words) - 1 else " ")
                yield f"data: {json.dumps({'type': 'token', 'content': word_token})}\n\n"
                await asyncio.sleep(0.003)

            # Final done event
            yield f"data: {json.dumps({'type': 'done', 'citations': citations, 'confidence': confidence, 'provider': provider_out, 'retrieval_debug': retrieval_debug, 'explanation': explanation, 'turn_id': turn_id, 'session_id': real_session_id})}\n\n"

        except Exception as ex:
            import json
            yield f"data: {json.dumps({'type': 'error', 'message': str(ex)})}\n\n"

    # Real fix 2026-08-24: carry forward whatever the rate-limit dependency
    # (and any other dependency using the shared `response` object) already
    # set — e.g. X-RateLimit-Limit/Remaining/Fallback — since this endpoint
    # returns its own StreamingResponse rather than the shared one.
    stream_headers = dict(response.headers)
    stream_headers.update({
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=stream_headers,
    )

@v6a_router.get("/health")
async def v6a_health():
    """Returns the health status of the v6a engine and backend dependencies."""
    from sqlalchemy import text
    db_ok = False
    try:
        from app.db.database import async_session_factory
        async with async_session_factory() as session:
            res = await session.execute(text("SELECT 1"))
            if res.scalar() == 1:
                db_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "online" if db_ok else "offline"
    }

class ChatFeedbackRequest(BaseModel):
    task_id: str
    tenant_id: str
    feedback: str # "up" or "down"
    comment: Optional[str] = None

@v6a_router.post("/feedback")
async def v6a_chat_feedback(req: ChatFeedbackRequest, token=Depends(require_authenticated_tenant)):
    """Stores RLHF feedback from the user for a specific chat turn.

    Real bug found via live testing 2026-08-22: this claimed "Feedback recorded"
    but only ever wrote a transient logger.info() line — no table existed, so
    every real thumbs up/down vanished the moment that log line rotated or the
    process restarted, despite the API telling the user it was durably saved.
    Now genuinely persisted in the real chat_feedback table (see schema.sql).
    """
    import logging
    from sqlalchemy import text as _text
    from app.db.database import async_session_factory as _asf
    real_tenant_id = verify_tenant_matches_token(req.tenant_id, token)
    logger = logging.getLogger("company_brain.feedback")
    try:
        async with _asf() as session:
            await session.execute(
                _text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": real_tenant_id}
            )
            await session.execute(
                _text("""
                    INSERT INTO chat_feedback (tenant_id, user_id, turn_id, feedback, comment)
                    VALUES (:tenant_id, :user_id, :turn_id, :feedback, :comment)
                """),
                {
                    "tenant_id": real_tenant_id,
                    "user_id": token.get("user_id", "unknown"),
                    "turn_id": req.task_id,
                    "feedback": req.feedback,
                    "comment": req.comment,
                },
            )
            await session.commit()
        logger.info(f"[Feedback] Task {req.task_id} ({real_tenant_id}): {req.feedback} - {req.comment}")
        return {"status": "success", "message": "Feedback recorded."}
    except Exception as ex:
        logger.error(f"[Feedback-Error] Failed to persist feedback for task {req.task_id}: {ex}")
        raise HTTPException(status_code=500, detail="Could not save feedback right now. Please try again.")

