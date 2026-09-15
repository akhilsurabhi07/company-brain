"""
Real Module 7 Agent Platform API — the missing surface for app/agent_platform/,
which had real domain models, a real tool registry, and a real planner but no
executor and no way for a real user to ever reach it.

Same real auth pattern as every other tenant-facing endpoint in this codebase:
require_authenticated_tenant + verify_tenant_matches_token, so a valid token
for tenant A can never submit or read tenant B's agent runs.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token
from app.agent_platform.executor import run_research_agent, get_execution

router = APIRouter(prefix="/api/v1/agents", tags=["Agent Platform"])


class RunResearchAgentRequest(BaseModel):
    tenant_id: Optional[str] = None
    request: str


@router.post("/research/run")
async def run_research_agent_endpoint(req: RunResearchAgentRequest, token=Depends(require_authenticated_tenant)):
    """Submits and runs a real research-agent execution synchronously (this
    agent's tools are all fast, read-only lookups — see executor.py's own
    note on why this isn't a background job yet)."""
    tenant_id = verify_tenant_matches_token(req.tenant_id, token)
    if not req.request or not req.request.strip():
        raise HTTPException(status_code=400, detail="request must not be empty.")
    result = await run_research_agent(tenant_id=tenant_id, user_id=token["user_id"], user_request=req.request.strip())
    return result.model_dump()


@router.get("/executions/{execution_id}")
async def get_execution_endpoint(execution_id: str, tenant_id: str, token=Depends(require_authenticated_tenant)):
    """Real per-execution ownership check via the explicit tenant_id filter in
    get_execution() — a nonexistent id and someone else's tenant's real id
    both come back 404, never a 403 that would confirm the id exists."""
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    execution = await get_execution(execution_id, tenant_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="No agent execution found with that ID.")
    return execution
