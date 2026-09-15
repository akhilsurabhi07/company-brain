"""
Real MCP (Model Context Protocol) server — Module 10, external AI connectivity.
====================================================================================
Hand-implemented JSON-RPC 2.0 over the Streamable HTTP transport (verified live
against modelcontextprotocol.io's 2025-06-18 spec, 2026-08-20) rather than the
official `mcp` Python SDK — the SDK's dependency chain pulls a Starlette major
version incompatible with this app's pinned FastAPI (0.104.1), which broke the
entire running application when tried. Reverted that install immediately; this
manual implementation avoids the conflict entirely while staying spec-compliant.

Scope, stated plainly rather than silently omitted: single JSON response per request
(the spec's simpler, fully-compliant option — "MUST either return
Content-Type: text/event-stream... or application/json"), no server-initiated SSE
stream, no session ID assignment (the spec says a server MAY assign one, not MUST —
skipped since these tools are stateless). A real production deployment wanting
streaming/resumability would build on top of this, not need to redo it.

Auth: a real per-tenant bearer key (see mcp_keys_router.py) resolves to a real
tenant_id — fails closed on anything invalid or revoked, same standard as the
gateway auth_handler.py fix earlier this session. Every tool call runs the exact
same real, already-verified HybridRetriever and tenant-scoped SQL the live chat
product uses — this is a new transport onto real functionality, not a new pipeline.
"""
import hashlib
import json
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, HTTPException, Header, Response
from sqlalchemy import text
from app.db.database import async_session_factory
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever

router = APIRouter(prefix="/mcp", tags=["MCP Server"])

PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "search_company_knowledge",
        "description": (
            "Searches this organization's real ingested knowledge (documents, tickets, messages) "
            "using hybrid vector + keyword retrieval with reranking. Returns real retrieved "
            "passages with their source document and score, or honestly reports no relevant "
            "results were found — never fabricates an answer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The natural-language question or search query."},
                "user_id": {"type": "string", "description": "Real identity of the person asking (e.g. their email or Slack/Drive user id) — used to enforce real per-document/per-channel access control. Omit only for queries that don't need restricted content."},
                "top_k": {"type": "integer", "description": "Max results to return (default 6)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_connected_sources",
        "description": "Lists which real data sources are actually connected and ingested for this tenant, with document counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


async def _resolve_tenant_from_bearer(authorization: Optional[str]) -> str:
    """Real key-hash lookup -> real tenant_id. Fails closed on anything invalid,
    missing, or revoked — no default/fallback identity, matching the gateway
    auth_handler.py fix from earlier this session."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")
    raw_key = authorization[len("Bearer "):].strip()
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    async with async_session_factory() as session:
        res = await session.execute(
            text("SELECT id, tenant_id FROM mcp_api_keys WHERE key_hash = :hash AND revoked_at IS NULL"),
            {"hash": key_hash},
        )
        row = res.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid or revoked MCP API key.")
        await session.execute(
            text("UPDATE mcp_api_keys SET last_used_at = now() WHERE id = :kid"),
            {"kid": row.id},
        )
        await session.commit()
    return str(row.tenant_id)


async def _call_tool(tenant_id: str, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "search_company_knowledge":
        query = arguments.get("query", "")
        if not query.strip():
            return {"content": [{"type": "text", "text": "A non-empty query is required."}], "isError": True}
        user_id = arguments.get("user_id", "")
        top_k = int(arguments.get("top_k", 6))

        result = await hybrid_retriever.search(tenant_id=tenant_id, query=query, top_k=top_k, user_id=user_id)
        chunks = result.get("chunks", [])
        if not chunks:
            return {"content": [{"type": "text", "text": "No relevant information was found in this organization's connected knowledge for that query."}], "isError": False}

        lines = []
        for c in chunks:
            lines.append(
                f"Source: {c.get('doc_title', 'Untitled')} ({c.get('source_app', 'unknown')}) "
                f"— relevance score {c.get('score', 0):.3f}\n{c.get('content', '')}"
            )
        return {"content": [{"type": "text", "text": "\n\n---\n\n".join(lines)}], "isError": False}

    elif name == "list_connected_sources":
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
            res = await session.execute(
                text("SELECT source_app, COUNT(*) FROM documents WHERE tenant_id = :tid GROUP BY source_app ORDER BY COUNT(*) DESC"),
                {"tid": tenant_id},
            )
            rows = res.fetchall()
        if not rows:
            return {"content": [{"type": "text", "text": "No data sources are ingested for this workspace yet."}], "isError": False}
        text_out = "\n".join(f"- {r[0]}: {r[1]} document(s)" for r in rows)
        return {"content": [{"type": "text", "text": text_out}], "isError": False}

    return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}


def _rpc_error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _rpc_result(req_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


@router.post("")
async def mcp_endpoint(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
):
    tenant_id = await _resolve_tenant_from_bearer(authorization)

    try:
        body = await request.json()
    except Exception:
        return _rpc_error(None, -32700, "Parse error: invalid JSON.")

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}
    is_notification = "id" not in body

    response.headers["MCP-Protocol-Version"] = PROTOCOL_VERSION

    if method == "initialize":
        return _rpc_result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "company-brain", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return Response(status_code=202)

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            call_result = await _call_tool(tenant_id, tool_name, arguments)
        except Exception as ex:
            return _rpc_error(req_id, -32000, f"Tool execution failed: {ex}")
        return _rpc_result(req_id, call_result)

    if is_notification:
        return Response(status_code=202)

    return _rpc_error(req_id, -32601, f"Method not found: {method}")
