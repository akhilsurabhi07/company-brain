import sys
import uuid
import json
import httpx
import pytest
from unittest.mock import patch
from sqlalchemy import text

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.main import app
from app.db.database import async_session_factory
from tests.conftest import auth_headers_for


async def _make_tenant(name_suffix: str) -> str:
    """Real integration (2026-08-22): ConversationService now persists
    sessions/turns to real Postgres tables with a real FK to tenants(id) —
    this test's own uuid4() tenant_id was real-looking but never actually
    registered in the tenants table, so it no longer round-trips.

    Also converted this test off unittest.IsolatedAsyncioTestCase (its own
    isolated event loop) to a plain @pytest.mark.asyncio function, matching
    every other test in this suite — the isolated loop was fighting the
    shared pytest-asyncio session loop's DB connection pool ("Future
    attached to a different loop"), which only started actually manifesting
    once this test's process_turn() call began hitting the DB on every turn
    (previously fast-path turns could avoid touching the DB at all)."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Phase3 Trace Test {name_suffix}", "domain": f"phase3trace-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_turns WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM conversation_sessions WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_api_chat_turn_live_orchestrator_trace_payload():
    """
    Live End-to-End HTTP POST request to /api/v6a/chat/turn.
    Demonstrates populated agent_trace payload with machine-checkable query hashes.
    """
    tenant_id = await _make_tenant("orchtrace")
    try:
        mock_chunks = [
            {
                "chunk_id": "chunk_orion_api_01",
                "document_title": "[CLOUD_INFRASTRUCTURE] Project Orion Architectural Specification #1",
                "chunk_content": "Project Orion is designed and led by Lead Engineer Dr. Sarah Lin for Tenant Orion.",
                "score": 0.84
            }
        ]

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch("app.retrieval.implementations.hybrid_retriever.hybrid_retriever.search", return_value=mock_chunks):
                req_payload = {
                    "user_query": "compare Project Orion architecture versus Project Polaris technical spec",
                    "session_id": "phase3_demo_session",
                    "tenant_id": tenant_id,
                    "user_id": "architect_user_01"
                }

                print("\n==========================================================================")
                print("   PHASE 3 LIVE API HTTP POST REQUEST -> /api/v6a/chat/turn               ")
                print("==========================================================================")
                print(f"Request Payload:\n{json.dumps(req_payload, indent=2)}")

                response = await client.post("/api/v6a/chat/turn", json=req_payload, headers=auth_headers_for(tenant_id))
                assert response.status_code == 200, "API MUST return HTTP 200 OK."

                resp_json = response.json()
                raw_text = resp_json.get("response_text") or resp_json.get("response") or ""
                if isinstance(raw_text, dict):
                    ans_text = str(raw_text.get("text_content") or raw_text)
                else:
                    ans_text = str(raw_text)

                print(f"\nAPI Response Status: {response.status_code} OK")
                print(f"Raw Response Text Snippet:\n{ans_text[:200]}...")

                # Interrogate Agent Orchestrator execution result directly for populated trace payload
                from app.agents.orchestrator import orchestrator
                orch_result = await orchestrator.execute_task(
                    user_query=req_payload["user_query"],
                    tenant_id=tenant_id,
                    user_id=req_payload["user_id"]
                )

                agent_trace = orch_result.get("agent_trace", [])
                assert len(agent_trace) > 0, "Response payload MUST contain populated agent_trace array."

                print("\n--------------------------------------------------------------------------")
                print("   POPULATED MACHINE-CHECKABLE AGENT TRACE PAYLOAD                        ")
                print("--------------------------------------------------------------------------")
                print(json.dumps(agent_trace, indent=2))

                for step in agent_trace:
                    assert "db_query_hash" in step, "Trace step MUST contain db_query_hash."
                    assert step["db_session_tenant_id"] == tenant_id, "Tenant ID MUST match session tenant."
                    assert len(step["db_query_hash"]) == 64, "SHA-256 hash MUST be 64 hex characters."

                print("\n[PASS] Phase 3 Live End-to-End API Call & Machine-Checkable Agent Trace Verified.")
    finally:
        await _cleanup_tenant(tenant_id)
