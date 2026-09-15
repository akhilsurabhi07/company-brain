"""
Real Tool Registry — Module 7.

Schema per tool mirrors the master architecture spec's required fields
(tool_id, description, risk_level, requires_approval, tenant_scope, timeout)
without yet building the full governance engine that spec describes — this is the
smallest real, correctly-shaped version, not the complete platform.

Both registered tools are read-only wrappers around already-real, already-tested
functionality (HybridRetriever, graph_decisions) — no new retrieval logic here,
per the master architecture's own rule: "Module 7 must not build another retrieval
system... use Module 5."
"""
import time
from typing import Any, Callable, Dict, Awaitable
from pydantic import BaseModel
from sqlalchemy import text
from app.db.database import async_session_factory


class ToolDefinition(BaseModel):
    tool_id: str
    name: str
    description: str
    risk_level: str  # "low" | "medium" | "high"
    requires_approval: bool
    tenant_scope: bool = True  # every tool here is mandatorily tenant-scoped
    timeout_seconds: int = 20


class ToolRegistry:
    def __init__(self):
        self._definitions: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}

    def register(self, definition: ToolDefinition, handler: Callable[..., Awaitable[Any]]) -> None:
        self._definitions[definition.tool_id] = definition
        self._handlers[definition.tool_id] = handler

    def get_definition(self, tool_id: str) -> ToolDefinition:
        return self._definitions[tool_id]

    def list_tools(self) -> list:
        return list(self._definitions.values())

    async def execute(self, tool_id: str, tenant_id: str, **kwargs) -> Dict[str, Any]:
        """Executes a real tool, returning a structured result. Never raises past this
        boundary — a tool failure is real data for the agent to observe and react to,
        not a crash."""
        definition = self._definitions.get(tool_id)
        if definition is None:
            return {"success": False, "output_summary": f"Unknown tool '{tool_id}'", "latency_ms": 0.0}

        handler = self._handlers[tool_id]
        t0 = time.time()
        try:
            result = await handler(tenant_id=tenant_id, **kwargs)
            latency = round((time.time() - t0) * 1000.0, 2)
            return {"success": True, "output_summary": result, "latency_ms": latency}
        except Exception as ex:
            latency = round((time.time() - t0) * 1000.0, 2)
            return {"success": False, "output_summary": f"Tool error: {ex}", "latency_ms": latency}


async def _search_company_knowledge(tenant_id: str, query: str) -> str:
    """Real wrapper around the already-real, already-tested HybridRetriever —
    no new retrieval logic, per the master architecture's own rule."""
    from app.retrieval.implementations.hybrid_retriever import hybrid_retriever

    res = await hybrid_retriever.search(query=query, tenant_id=tenant_id, top_k=5, user_id="agent")
    chunks = res.get("chunks", []) if isinstance(res, dict) else res
    if not chunks:
        return "No matching company knowledge found for this query."

    lines = []
    for c in chunks[:5]:
        title = c.get("doc_title") or c.get("document_title") or "Untitled"
        content = (c.get("content") or c.get("chunk_content") or "")[:400]
        lines.append(f"[{title}] {content}")
    return "\n\n".join(lines)


async def _get_decisions(tenant_id: str, topic: str = "") -> str:
    """Real query against graph_decisions — explicit tenant_id filter (not RLS-only),
    same defense-in-depth pattern used throughout this project."""
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        if topic:
            res = await session.execute(
                text("""
                    SELECT decision_title, rationale, actual_outcome, state FROM graph_decisions
                    WHERE tenant_id = :tid AND (decision_title ILIKE :pat OR rationale ILIKE :pat)
                    ORDER BY created_at DESC LIMIT 10
                """),
                {"tid": tenant_id, "pat": f"%{topic}%"},
            )
        else:
            res = await session.execute(
                text("""
                    SELECT decision_title, rationale, actual_outcome, state FROM graph_decisions
                    WHERE tenant_id = :tid ORDER BY created_at DESC LIMIT 10
                """),
                {"tid": tenant_id},
            )
        rows = res.fetchall()

    if not rows:
        return "No real decisions recorded for this tenant yet."
    return "\n\n".join(
        f"Decision: {r.decision_title}\nOutcome: {r.actual_outcome or 'pending'} ({r.state})\nRationale: {(r.rationale or '')[:300]}"
        for r in rows
    )


tool_registry = ToolRegistry()
tool_registry.register(
    ToolDefinition(
        tool_id="search_company_knowledge",
        name="Search Company Knowledge",
        description="Searches the tenant's real ingested documents via hybrid vector+keyword retrieval.",
        risk_level="low",
        requires_approval=False,
    ),
    _search_company_knowledge,
)
tool_registry.register(
    ToolDefinition(
        tool_id="get_decisions",
        name="Get Decisions",
        description="Looks up real recorded decisions (from GitHub/Jira resolution) for this tenant, optionally filtered by topic.",
        risk_level="low",
        requires_approval=False,
    ),
    _get_decisions,
)
