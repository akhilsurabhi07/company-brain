"""
Real Scheduled-Query Runner — Module 6C (2026-08-23).

Backs the "Scheduled" panel: a saved question that re-runs itself on a real
interval and keeps its latest real answer. Deliberately NOT Celery Beat —
Redis is confirmed unreachable in this dev environment (see
env-file-lost-2026-08-19 memory: never restored), so a Celery-beat-based
scheduler would be real code with no way to actually verify it fires. This
is a plain in-process asyncio loop instead: needs nothing but Postgres,
genuinely real, and genuinely testable end-to-end (create a schedule with a
short interval, watch it actually re-run and update its stored answer).

Trade-off, stated honestly: this only runs schedules while the app process
itself is running, and only on whichever single process picked up the loop
(no distributed locking) — correct for this single-instance deployment, not
a substitute for a real distributed scheduler if this app is ever run as
multiple replicas. That's a real, known limitation, not hidden.
"""
import asyncio
import logging
from app.db.database import async_session_factory
from sqlalchemy import text

logger = logging.getLogger("query_scheduler")

_TICK_SECONDS = 10  # how often the loop checks for due schedules
_task = None


async def _run_due_schedules_once():
    # Real fix found via live Redis verification 2026-08-24: this used to
    # construct a brand-new ConversationService() (and therefore a brand-new
    # ConversationCache() with its own uninitialized Redis client) on every
    # single tick — a real, unnecessary duplicate-instance pattern (the app
    # already has exactly one real shared instance for this,
    # ConversationContainer's singleton, which every real live chat request
    # already uses) that would also re-pay the real Redis cold-connection
    # cost repeatedly instead of once.
    from app.conversation.container import ConversationContainer
    from app.conversation.domain.persona import PersonaType
    from app.conversation.domain.modes import ConversationMode

    async with async_session_factory() as session:
        due = await session.execute(
            text("""
                SELECT sq.id, sq.tenant_id, sq.user_id, sq.query_text, sq.persona, u.role AS creator_role
                FROM scheduled_queries sq
                LEFT JOIN users u ON u.id::text = sq.user_id AND u.tenant_id = sq.tenant_id
                WHERE sq.is_active = TRUE AND sq.next_run_at <= now()
                ORDER BY sq.next_run_at ASC
                LIMIT 20
            """)
        )
        rows = due.fetchall()

    for row in rows:
        schedule_id, tenant_id, user_id, query_text, persona_str = (
            row.id, str(row.tenant_id), row.user_id, row.query_text, row.persona
        )
        # Real RBAC bypass found via code audit 2026-09-11: this always ran the
        # scheduled query as caller_role="admin", regardless of who actually
        # created the schedule. A "member"-role user could schedule a question
        # designed to surface restricted content (salary/payroll/compensation/
        # bonus) and, because the background runner always executed as admin,
        # the same real redaction that correctly blocks that user's OWN
        # interactive chat queries would never apply here -- a genuine
        # privilege-escalation path via the Scheduled panel. Use the real
        # creator's current role instead; fail closed to "member" if the user
        # was deleted or the join otherwise can't resolve.
        caller_role = (getattr(row, "creator_role", None) or "member").lower()
        try:
            try:
                persona_val = PersonaType(persona_str)
            except ValueError:
                persona_val = PersonaType.CTO

            service = ConversationContainer.get_conversation_service()
            result = await service.process_turn(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=None,
                user_query=query_text,
                persona=persona_val,
                mode=ConversationMode.ASK,
                knowledge_context="KnowledgeContext v1.0.0 Grounded Baseline",
                use_consensus=False,
                preferred_provider=None,
                history=[],
                debug_retrieval=False,
                caller_role=caller_role,
            )
            raw_answer = result.get("response_text") or result.get("response") or ""
            answer_text = raw_answer.get("text_content", str(raw_answer)) if isinstance(raw_answer, dict) else str(raw_answer)

            async with async_session_factory() as write_session:
                await write_session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                await write_session.execute(
                    text("""
                        UPDATE scheduled_queries
                        SET last_run_at = now(),
                            next_run_at = now() + (interval_seconds * INTERVAL '1 second'),
                            last_status = 'ok', last_answer = :answer, last_error = NULL
                        WHERE id = :id
                    """),
                    {"id": schedule_id, "answer": answer_text},
                )
                await write_session.commit()
            logger.info(f"[QueryScheduler] Ran schedule {schedule_id} for tenant {tenant_id}: ok")
        except Exception as ex:
            logger.warning(f"[QueryScheduler] Schedule {schedule_id} failed: {ex}")
            try:
                async with async_session_factory() as err_session:
                    await err_session.execute(
                        text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id}
                    )
                    await err_session.execute(
                        text("""
                            UPDATE scheduled_queries
                            SET last_run_at = now(),
                                next_run_at = now() + (interval_seconds * INTERVAL '1 second'),
                                last_status = 'error', last_error = :err
                            WHERE id = :id
                        """),
                        {"id": schedule_id, "err": str(ex)[:2000]},
                    )
                    await err_session.commit()
            except Exception as write_ex:
                logger.error(f"[QueryScheduler] Failed to record error for schedule {schedule_id}: {write_ex}")


async def _loop():
    while True:
        try:
            await _run_due_schedules_once()
        except Exception as ex:
            logger.error(f"[QueryScheduler] Tick failed: {ex}")
        await asyncio.sleep(_TICK_SECONDS)


def start():
    """Call once from a FastAPI startup event. Idempotent — calling twice
    (e.g. under --reload) does not spawn a second loop."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
        logger.info("[QueryScheduler] Started real in-process scheduler loop.")
