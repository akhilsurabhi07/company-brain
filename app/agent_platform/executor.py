"""
Real Agent Executor — Module 7.

Completes the loop the rest of app/agent_platform/ was built for but never
finished: plan (planner.py) -> execute each step against the real tool
registry (tool_registry.py) -> synthesize a final answer -> persist the
whole run to the real `agent_executions` table (already in schema.sql,
RLS-protected, but unreferenced by any Python code until this file).

No new retrieval or LLM plumbing here, same rule as the rest of this
package: this only orchestrates already-real, already-tested pieces.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import text
from app.db.database import async_session_factory
from app.agent_platform.domain import (
    AgentExecutionState, AgentExecutionResult, ToolCallRecord,
)
from app.agent_platform.planner import create_plan
from app.agent_platform.tool_registry import tool_registry
from app.conversation.runtime.orchestrator import RuntimeOrchestrator
from app.conversation.interfaces.llm_provider import GenerationRequest

_orchestrator = RuntimeOrchestrator()

_SYNTHESIS_SYSTEM_PROMPT = """You are a research agent reporting back on what you found. \
You were given a request and ran real tools against the company's real data. Write a clear, \
direct answer using ONLY the tool output provided below — never invent a fact that isn't in \
it. If the tool output doesn't actually answer the request, say so honestly rather than \
guessing."""


async def _persist(execution_id: str, tenant_id: str, **fields):
    """Real, explicit tenant_id-filtered write — same defense-in-depth pattern as
    every other real query in this codebase, not just relying on RLS alone."""
    if not fields:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        await session.execute(
            text(f"UPDATE agent_executions SET {set_clause} WHERE id = :id AND tenant_id = :tid"),
            {**fields, "id": execution_id, "tid": tenant_id},
        )
        await session.commit()


async def run_research_agent(tenant_id: str, user_id: str, user_request: str) -> AgentExecutionResult:
    """Real, synchronous end-to-end run (no background task queue yet — that's
    real future scope once a run can take long enough or act consequentially
    enough to need one; this agent's tools are all fast, read-only lookups)."""
    execution_id = str(uuid.uuid4())

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        await session.execute(
            text("""
                INSERT INTO agent_executions (id, tenant_id, user_id, agent_type, user_request, state)
                VALUES (:id, :tid, :uid, 'research', :req, 'CREATED')
            """),
            {"id": execution_id, "tid": tenant_id, "uid": user_id, "req": user_request},
        )
        await session.commit()

    try:
        # ── PLANNING ──
        await _persist(execution_id, tenant_id, state=AgentExecutionState.PLANNING.value)
        plan = await create_plan(user_request, tenant_id, user_id)
        await _persist(execution_id, tenant_id, plan=json.dumps(plan.model_dump()))

        # ── EXECUTING / OBSERVING each step ──
        await _persist(execution_id, tenant_id, state=AgentExecutionState.EXECUTING.value)
        tool_records = []
        tool_outputs_for_synthesis = []
        for step in plan.steps:
            raw = await tool_registry.execute(step.tool_id, tenant_id=tenant_id, **step.tool_input)
            record = ToolCallRecord(
                tool_id=step.tool_id,
                tool_input=step.tool_input,
                output_summary=str(raw["output_summary"])[:2000],
                success=raw["success"],
                latency_ms=raw["latency_ms"],
            )
            tool_records.append(record)
            tool_outputs_for_synthesis.append(f"Tool: {step.tool_id}\nReasoning: {step.reasoning}\nResult:\n{record.output_summary}")
            await _persist(
                execution_id, tenant_id,
                state=AgentExecutionState.OBSERVING.value,
                steps=json.dumps([r.model_dump() for r in tool_records]),
            )

        # ── SYNTHESIS: same real LLM cascade the planner uses, no new plumbing ──
        synthesis_input = f"Original request: {user_request}\n\n" + "\n\n---\n\n".join(tool_outputs_for_synthesis)
        gen_req = GenerationRequest(
            prompt=synthesis_input, raw_query=user_request,
            system_prompt=_SYNTHESIS_SYSTEM_PROMPT, model_name="gpt-4o",
            temperature=0.3, max_tokens=700, tenant_id=tenant_id, user_id=user_id,
        )
        gen_res = await _orchestrator.execute_generation(gen_req)
        final_result = gen_res.payload.text_content.strip()

        # Real bug found via live verification 2026-09-15: this passed a plain
        # string (time.strftime(...)) for a timestamptz column bound through
        # raw parameterized SQL. psycopg2 would auto-cast a string like this,
        # but asyncpg (this project's real driver) requires an actual
        # datetime object -- every real agent run, success or failure, was
        # crashing right here at the final persist step with
        # "invalid input for query argument $3: ... expected a datetime.date
        # or datetime.datetime instance, got 'str'". The FAILED branch below
        # had the identical bug, so a run that failed for any other reason
        # would ALSO crash while trying to record that failure, masking the
        # real error behind this one. Fixed by passing a real datetime.
        await _persist(
            execution_id, tenant_id,
            state=AgentExecutionState.COMPLETED.value,
            final_result=final_result,
            completed_at=datetime.now(timezone.utc),
        )
        return AgentExecutionResult(
            execution_id=execution_id, state=AgentExecutionState.COMPLETED,
            plan=plan, steps=tool_records, final_result=final_result,
        )
    except Exception as ex:
        await _persist(
            execution_id, tenant_id,
            state=AgentExecutionState.FAILED.value,
            error_message=str(ex)[:2000],
            completed_at=datetime.now(timezone.utc),
        )
        return AgentExecutionResult(
            execution_id=execution_id, state=AgentExecutionState.FAILED, error_message=str(ex),
        )


async def get_execution(execution_id: str, tenant_id: str) -> Optional[dict]:
    """Real status/result poll — explicit tenant_id filter so one tenant can never
    read another tenant's agent run by guessing/incrementing an execution_id."""
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        res = await session.execute(
            text("""
                SELECT id, agent_type, user_request, state, plan, steps, final_result,
                       error_message, created_at, completed_at
                FROM agent_executions WHERE id = :id AND tenant_id = :tid
            """),
            {"id": execution_id, "tid": tenant_id},
        )
        row = res.fetchone()
    if not row:
        return None
    return {
        "execution_id": str(row.id), "agent_type": row.agent_type, "user_request": row.user_request,
        "state": row.state, "plan": row.plan, "steps": row.steps, "final_result": row.final_result,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }
