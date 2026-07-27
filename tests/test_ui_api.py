import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_step1_signup_and_login():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unique_id = str(uuid.uuid4())[:8]
        signup_payload = {
            "company_name": f"Test Acme {unique_id}",
            "company_domain": f"testacme{unique_id}.com",
            "email": f"admin@{unique_id}.com",
            "password": "TestPassword123!",
            "full_name": "Acme Admin"
        }
        res_signup = await client.post("/api/v1/auth/signup", json=signup_payload)
        assert res_signup.status_code == 200
        data_signup = res_signup.json()
        assert data_signup["status"] == "success"
        assert "tenant_id" in data_signup
        tenant_id = data_signup["tenant_id"]

        login_payload = {
            "email": f"admin@{unique_id}.com",
            "password": "TestPassword123!"
        }
        res_login = await client.post("/api/v1/auth/login", json=login_payload)
        assert res_login.status_code == 200
        data_login = res_login.json()
        assert data_login["tenant_id"] == tenant_id

@pytest.mark.asyncio
async def test_step2_connectors_and_token_encryption():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tenant_id = "00000000-0000-0000-0000-000000000001"
        
        conn_res = await client.post("/api/v1/connectors/connect", json={
            "tenant_id": tenant_id,
            "source_app": "slack",
            "action": "connect"
        })
        assert conn_res.status_code == 200

        list_res = await client.get(f"/api/v1/connectors/list?tenant_id={tenant_id}")
        assert list_res.status_code == 200
        connectors = list_res.json()["connectors"]
        slack_card = next(c for c in connectors if c["id"] == "slack")
        assert slack_card["is_connected"] is True

@pytest.mark.asyncio
async def test_step3_and_4_ingestion_and_telemetry():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tenant_id = "00000000-0000-0000-0000-000000000001"

        start_res = await client.post("/api/v1/ingestion/start", json={"tenant_id": tenant_id})
        assert start_res.status_code == 200

        status_res = await client.get(f"/api/v1/ingestion/status?tenant_id={tenant_id}")
        assert status_res.status_code == 200
        telemetry = status_res.json()
        assert "total_documents_synced" in telemetry
        assert "total_s3_bytes" in telemetry
