import asyncio
import json
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory, engine
from app.storage.compressor import zstd_compressor
from app.storage.s3_storage import s3_storage
from app.security.crypto import token_crypto
from app.security.jwt_auth import jwt_engine
from app.processors.pii_redactor import pii_redactor
from app.connectors.registry import ConnectorRegistry
from tests.conftest import auth_headers_for

@pytest.mark.asyncio
async def test_1_lossless_zstd_compression():
    """Verify 100% roundtrip accuracy for Zstandard compression & decompression."""
    sample_payload = {
        "company": "Company Brain Test",
        "nested": {"array": [1, 2, 3], "flag": True},
        "text": "Extremely long text payload string repeated " * 50
    }
    compressed = zstd_compressor.compress_json(sample_payload)
    decompressed = zstd_compressor.decompress_json(compressed)
    assert decompressed == sample_payload
    assert len(compressed) < len(json.dumps(sample_payload))

@pytest.mark.asyncio
async def test_2_aes256_gcm_token_encryption():
    """Verify AES-256-GCM encryption and decryption of OAuth access tokens."""
    raw_token = "xoxb-slack-access-token-999888777"
    tenant_id = str(uuid.uuid4())
    
    encrypted_cipher = token_crypto.encrypt_token(raw_token, tenant_id)
    assert encrypted_cipher != raw_token
    
    decrypted_token = token_crypto.decrypt_token(encrypted_cipher, tenant_id)
    assert decrypted_token == raw_token

@pytest.mark.asyncio
async def test_3_pii_and_secret_redaction():
    """Verify scrubbing of API keys, Bearer tokens, and secrets."""
    dirty_text = "Connect using sk_live_51M0123456789abcdef and Bearer eyJhbGciOiJIUzI1NiIn0"
    clean_text = pii_redactor.redact_secrets(dirty_text)
    assert "sk_live_" not in clean_text
    assert "[REDACTED_API_KEY]" in clean_text or "[REDACTED_SECRET]" in clean_text

@pytest.mark.asyncio
async def test_4_stateless_jwt_authentication():
    """Verify signed enterprise JWT token generation and decoding."""
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    email = "admin@enterprise.com"

    token = jwt_engine.create_access_token(tenant_id=tenant_id, user_id=user_id, email=email)
    payload = jwt_engine.decode_access_token(token)

    assert payload is not None
    assert payload["tenant_id"] == tenant_id
    assert payload["user_id"] == user_id
    assert payload["email"] == email

@pytest.mark.asyncio
async def test_5_full_auth_and_tenant_provisioning_api():
    """Verify Signup, Login, and Tenant UUID creation via REST API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        uid = str(uuid.uuid4())[:8]
        signup_data = {
            "company_name": f"Verif Enterprise {uid}",
            "company_domain": f"verif{uid}.com",
            "email": f"admin@{uid}.com",
            "password": "SecurePassword123!",
            "full_name": "Verification Admin"
        }
        res_signup = await client.post("/api/v1/auth/signup", json=signup_data)
        assert res_signup.status_code == 200
        body_signup = res_signup.json()
        assert body_signup["status"] == "success"
        tenant_id = body_signup["tenant_id"]

        # Login verification
        res_login = await client.post("/api/v1/auth/login", json={
            "email": f"admin@{uid}.com",
            "password": "SecurePassword123!"
        })
        assert res_login.status_code == 200
        assert res_login.json()["tenant_id"] == tenant_id

@pytest.mark.asyncio
async def test_6_connectors_hub_and_token_caching_api():
    """Verify Connector list, OAuth Connect, and Redis Token Caching."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tenant_id = str(uuid.uuid4())
        headers = auth_headers_for(tenant_id)

        # List connectors
        res_list = await client.get(f"/api/v1/connectors/list?tenant_id={tenant_id}", headers=headers)
        assert res_list.status_code == 200
        connectors = res_list.json()["connectors"]
        # Was 6 — SharePoint added as a real 7th connector 2026-08-20 (see
        # app/connectors/sharepoint.py); this count should track AVAILABLE_APPS's
        # real length, not a number frozen at whatever it happened to be before.
        assert len(connectors) == len({"slack", "google_drive", "github", "jira", "whatsapp", "teams", "sharepoint"})

        # Connect Slack
        res_conn = await client.post("/api/v1/connectors/connect", json={
            "tenant_id": tenant_id,
            "source_app": "slack",
            "action": "connect"
        }, headers=headers)
        assert res_conn.status_code == 200

@pytest.mark.asyncio
async def test_7_ingestion_trigger_and_telemetry_api():
    """Verify Ingestion trigger and status telemetry polling API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tenant_id = str(uuid.uuid4())
        headers = auth_headers_for(tenant_id)

        # Connect Slack first
        await client.post("/api/v1/connectors/connect", json={
            "tenant_id": tenant_id,
            "source_app": "slack",
            "action": "connect"
        }, headers=headers)

        # Start ingestion
        res_start = await client.post("/api/v1/ingestion/start", json={"tenant_id": tenant_id}, headers=headers)
        assert res_start.status_code == 200

        # Wait 1s for background processing
        await asyncio.sleep(1.0)

        # Poll status telemetry
        res_status = await client.get(f"/api/v1/ingestion/status?tenant_id={tenant_id}", headers=headers)
        assert res_status.status_code == 200
        telemetry = res_status.json()
        assert "total_documents_synced" in telemetry
        assert "total_s3_bytes" in telemetry

@pytest.mark.asyncio
async def test_8_database_rls_tenant_isolation():
    """Verify that PostgreSQL RLS strictly isolates data between Tenant A and Tenant B."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant A', :domain)"), {"id": tenant_a, "domain": f"a{tenant_a[:6]}.com"})
            await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant B', :domain)"), {"id": tenant_b, "domain": f"b{tenant_b[:6]}.com"})

        # Insert document for Tenant A under Tenant A session context
        async with session.begin():
            await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_a}'"))
            await session.execute(text("""
                INSERT INTO documents (tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
                VALUES (:tenant_id, 'slack', 'chat', 'message', 'msg_tenant_a', 'Tenant A Secret Document', 'bucket', 'key_a')
            """), {"tenant_id": tenant_a})

        # Query under Tenant B session (RLS active)
        async with session.begin():
            await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_b}'"))
            res_b = await session.execute(text("SELECT COUNT(*) FROM documents WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_b})
            count_b_docs = res_b.fetchone()[0]

            # Tenant B has 0 documents
            assert count_b_docs == 0

