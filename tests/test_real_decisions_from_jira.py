"""Real test for Jira resolved-issue -> real Decision record extraction, 2026-08-20.

Same fix pattern as the GitHub PR decision extraction: graph_decisions had real write
methods but nothing in the live path called them for Jira. Also proves the owner_id
UUID-resolution fix (built for GitHub) works unchanged for Jira, since both connectors
use the same `user_{identifier}` graph-node-id convention.
"""
import json
import uuid
import pytest
import respx
import httpx
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.crypto import token_crypto
from app.config import settings
from app.api.ingestion_router import run_tenant_ingestion_pipeline

ATLASSIAN_API_BASE = "https://api.atlassian.com/ex/jira"


@pytest.fixture(autouse=True)
def _fake_jira_oauth_credentials(monkeypatch):
    monkeypatch.setattr(settings, "JIRA_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "JIRA_OAUTH_CLIENT_SECRET", "test-client-secret")


async def _make_tenant_with_jira_refresh_token(name: str, cloud_id: str = "CLOUD_DEC") -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": name, "d": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        encrypted = token_crypto.encrypt_token("fake-original-refresh-token", tenant_id)
        await session.execute(
            text("INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config) VALUES (:t, 'jira', :tok, CAST(:cfg AS jsonb))"),
            {"t": tenant_id, "tok": encrypted, "cfg": json.dumps({"cloud_id": cloud_id})},
        )
        await session.execute(
            text("INSERT INTO sync_statuses (tenant_id, source_app, status) VALUES (:t, 'jira', 'idle')"),
            {"t": tenant_id},
        )
        await session.commit()
    return tenant_id


def _mock_jira_api(cloud_id: str, resolution_name: str):
    respx.post("https://auth.atlassian.com/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "fake-access-token", "refresh_token": "rotated-token", "expires_in": 3600})
    )
    respx.get(f"{ATLASSIAN_API_BASE}/{cloud_id}/rest/api/3/search").mock(
        return_value=httpx.Response(200, json={
            "total": 1,
            "issues": [{
                "key": "ENG-99",
                "fields": {
                    "summary": "Database migration causing intermittent timeouts",
                    "description": {"type": "doc", "version": 1, "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Root cause was a missing index on the orders table."}]}
                    ]},
                    "project": {"key": "ENG", "name": "Engineering"},
                    "status": {"name": "Done"},
                    "assignee": {"accountId": "ACC_CARLA", "displayName": "Carla"},
                    "reporter": {"accountId": "ACC_BOB", "displayName": "Bob"},
                    "updated": "2026-08-01T00:00:00Z",
                    "resolution": {"name": resolution_name},
                    "resolutiondate": "2026-08-02T00:00:00Z",
                },
            }],
        })
    )
    respx.get(f"{ATLASSIAN_API_BASE}/{cloud_id}/rest/api/3/project/ENG/role").mock(
        return_value=httpx.Response(200, json={})
    )


@pytest.mark.asyncio
@respx.mock
async def test_resolved_ticket_creates_real_decision_with_resolved_uuid_owner():
    cloud_id = "CLOUD_DEC1"
    tenant_id = await _make_tenant_with_jira_refresh_token("Jira Decisions Test", cloud_id)
    _mock_jira_api(cloud_id, resolution_name="Done")

    await run_tenant_ingestion_pipeline(tenant_id)

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        row = (await session.execute(
            text("SELECT decision_title, owner_id, rationale, actual_outcome, state FROM graph_decisions WHERE tenant_id = :t"),
            {"t": tenant_id},
        )).fetchone()
        assert row is not None, "A real resolved Jira issue must create a real graph_decisions row."
        assert "Database migration" in row.decision_title
        assert "missing index" in row.rationale
        assert row.actual_outcome == "Done"
        assert row.state == "Published"

        assert row.owner_id is not None
        owner_entity = (await session.execute(
            text("SELECT canonical_name FROM graph_entities WHERE id = :id"), {"id": row.owner_id}
        )).fetchone()
        # Real display name ("Carla"), not the opaque account id — see the
        # canonical_name fallback-chain fix in ingestion_router.py (2026-08-20).
        assert owner_entity is not None and owner_entity.canonical_name == "Carla"


@pytest.mark.asyncio
@respx.mock
async def test_wont_fix_resolution_is_recorded_as_rejected():
    cloud_id = "CLOUD_DEC2"
    tenant_id = await _make_tenant_with_jira_refresh_token("Jira Decisions Rejected Test", cloud_id)
    _mock_jira_api(cloud_id, resolution_name="Won't Fix")

    await run_tenant_ingestion_pipeline(tenant_id)

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        row = (await session.execute(
            text("SELECT actual_outcome, state FROM graph_decisions WHERE tenant_id = :t"), {"t": tenant_id}
        )).fetchone()

    assert row is not None
    assert row.actual_outcome == "Won't Fix"
    assert row.state == "Rejected"
