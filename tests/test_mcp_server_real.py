"""Real, fully end-to-end MCP server tests — no mocking anywhere.

Unlike the connector tests, there's no third-party API to mock here: this is our own
server, hit via the real FastAPI app (httpx.ASGITransport), exercising the real key
generation/hashing, real bearer auth resolution, real JSON-RPC dispatch, and the real
(already-verified) HybridRetriever underneath search_company_knowledge. This is the
same rigor standard as everything else, just with a shorter honesty disclaimer because
there's genuinely nothing external left to fake.
"""
import uuid
import httpx
import pytest
from sqlalchemy import text
from app.main import app
from app.db.database import async_session_factory
from app.processors.ingestion_pipeline import chunk_embed_and_store
from tests.conftest import auth_headers_for

MCP_URL = "/mcp"


async def _make_tenant(name: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": name, "d": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        await session.commit()
    return tenant_id


async def _create_mcp_key(client: httpx.AsyncClient, tenant_id: str) -> str:
    resp = await client.post(
        "/api/v1/mcp/keys", json={"tenant_id": tenant_id, "name": "Test Key"}, headers=auth_headers_for(tenant_id)
    )
    assert resp.status_code == 200
    return resp.json()["api_key"]


@pytest.mark.asyncio
async def test_missing_auth_is_rejected():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_key_is_rejected():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}, headers={"Authorization": "Bearer cbmcp_totally-fake-key"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_revoked_key_is_rejected():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        tenant_id = await _make_tenant("MCP Revoke Test")
        jwt_headers = auth_headers_for(tenant_id)
        create_resp = await client.post("/api/v1/mcp/keys", json={"tenant_id": tenant_id}, headers=jwt_headers)
        key_id, api_key = create_resp.json()["id"], create_resp.json()["api_key"]

        # Real key works before revocation.
        resp1 = await client.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}, headers={"Authorization": f"Bearer {api_key}"})
        assert resp1.status_code == 200

        revoke_resp = await client.delete(f"/api/v1/mcp/keys/{key_id}", params={"tenant_id": tenant_id}, headers=jwt_headers)
        assert revoke_resp.status_code == 200

        resp2 = await client.post(MCP_URL, json={"jsonrpc": "2.0", "id": 2, "method": "initialize"}, headers={"Authorization": f"Bearer {api_key}"})
        assert resp2.status_code == 401


@pytest.mark.asyncio
async def test_initialize_and_tools_list_real_handshake():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        tenant_id = await _make_tenant("MCP Handshake Test")
        api_key = await _create_mcp_key(client, tenant_id)
        headers = {"Authorization": f"Bearer {api_key}"}

        init_resp = await client.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, headers=headers)
        assert init_resp.status_code == 200
        init_body = init_resp.json()
        assert init_body["result"]["serverInfo"]["name"] == "company-brain"

        list_resp = await client.post(MCP_URL, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)
        tools = list_resp.json()["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        assert "search_company_knowledge" in tool_names
        assert "list_connected_sources" in tool_names


@pytest.mark.asyncio
async def test_search_tool_retrieves_real_ingested_content_and_enforces_real_acl():
    """The real end-to-end proof: ingest a real document with a real per-document ACL,
    then call the MCP tool as a permitted user (finds it) and a random outsider
    (doesn't) — same enforcement the live chat product gets, now reachable via MCP."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        tenant_id = await _make_tenant("MCP Search Test")
        api_key = await _create_mcp_key(client, tenant_id)
        headers = {"Authorization": f"Bearer {api_key}"}

        doc_id = str(uuid.uuid4())
        content = "Incident postmortem: the checkout service outage was caused by a database connection pool exhaustion."
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(
                text("""
                    INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type,
                        external_id, title, content, s3_bucket, s3_key, is_compressed, file_size_bytes)
                    VALUES (:id, :t, 'upload', 'doc', 'file', :ext, 'Checkout Outage Postmortem', :content, 'b', 'k', TRUE, :sz)
                """),
                {"id": doc_id, "t": tenant_id, "ext": "ext1", "content": content, "sz": len(content)},
            )
            await session.execute(
                text("INSERT INTO document_acls (document_id, tenant_id, principal_type, principal_external_id, permission) VALUES (:d, :t, 'user', 'alice@example.com', 'read')"),
                {"d": doc_id, "t": tenant_id},
            )
            await session.commit()
        result = await chunk_embed_and_store(tenant_id=tenant_id, document_id=doc_id, full_text=content, resource_category="doc")
        assert result["status"] == "completed"

        # Permitted user finds it via the real MCP tool call.
        call_resp = await client.post(MCP_URL, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "search_company_knowledge", "arguments": {"query": "checkout service outage cause", "user_id": "alice@example.com"}},
        }, headers=headers)
        assert call_resp.status_code == 200
        call_body = call_resp.json()["result"]
        assert call_body["isError"] is False
        assert "database connection pool" in call_body["content"][0]["text"]

        # A real outsider (not on the ACL) gets an honest "nothing found", not the restricted content.
        outsider_resp = await client.post(MCP_URL, json={
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "search_company_knowledge", "arguments": {"query": "checkout service outage cause", "user_id": "mallory@example.com"}},
        }, headers=headers)
        outsider_body = outsider_resp.json()["result"]
        assert "database connection pool" not in outsider_body["content"][0]["text"]


@pytest.mark.asyncio
async def test_list_connected_sources_tool_is_real_and_per_tenant():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        tenant_a = await _make_tenant("MCP Sources Test A")
        tenant_b = await _make_tenant("MCP Sources Test B")
        key_a = await _create_mcp_key(client, tenant_a)

        doc_id = str(uuid.uuid4())
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_a})
            await session.execute(
                text("""
                    INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type,
                        external_id, title, content, s3_bucket, s3_key, is_compressed, file_size_bytes)
                    VALUES (:id, :t, 'github', 'doc', 'readme', 'ext1', 'Real README', 'real content', 'b', 'k', TRUE, 12)
                """),
                {"id": doc_id, "t": tenant_a},
            )
            await session.commit()

        resp = await client.post(MCP_URL, json={
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "list_connected_sources", "arguments": {}},
        }, headers={"Authorization": f"Bearer {key_a}"})
        text_out = resp.json()["result"]["content"][0]["text"]
        assert "github: 1 document" in text_out

        # A key issued for tenant B must never see tenant A's real source inventory.
        key_b = await _create_mcp_key(client, tenant_b)
        resp_b = await client.post(MCP_URL, json={
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "list_connected_sources", "arguments": {}},
        }, headers={"Authorization": f"Bearer {key_b}"})
        text_out_b = resp_b.json()["result"]["content"][0]["text"]
        assert "github" not in text_out_b
