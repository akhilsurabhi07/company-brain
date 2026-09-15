"""Real test for GitHub PR -> real Decision record extraction, 2026-08-20.

Pins down the fix: graph_decisions had real write methods (postgres_knowledge_repo.
create_decision) but nothing in the live ingestion path ever called them — the table
was permanently empty for every tenant, same root cause as the entities/relationships
gap fixed earlier. Uses respx to mock only the GitHub API boundary; the rest (real
ingestion pipeline, real DecisionModel persistence, real idempotency check) is genuine.
"""
import uuid
import pytest
import respx
import httpx
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.crypto import token_crypto
from app.api.ingestion_router import run_tenant_ingestion_pipeline

GITHUB_API_BASE = "https://api.github.com"


async def _make_tenant_with_github_token(name: str, owner: str, repo: str) -> str:
    import json
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :n, :d)"),
            {"id": tenant_id, "n": name, "d": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        encrypted = token_crypto.encrypt_token("ghp_fake_but_well_formed_test_token", tenant_id)
        await session.execute(
            text("INSERT INTO oauth_tokens (tenant_id, source_app, encrypted_access_token, config) VALUES (:t, 'github', :tok, CAST(:cfg AS jsonb))"),
            {"t": tenant_id, "tok": encrypted, "cfg": json.dumps({"owner": owner, "repo": repo})},
        )
        await session.execute(
            text("INSERT INTO sync_statuses (tenant_id, source_app, status) VALUES (:t, 'github', 'idle')"),
            {"t": tenant_id},
        )
        await session.commit()
    return tenant_id


def _mock_github_api(owner: str, repo: str, merged: bool):
    respx.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls").mock(
        return_value=httpx.Response(200, json=[{
            "id": 1, "number": 42, "title": "Add real rate limiting to the ingestion API",
            "state": "closed", "body": "We were getting hammered by a single misbehaving tenant. This adds a real per-tenant token bucket.",
            "user": {"login": "octocat", "avatar_url": ""},
            "head": {"ref": "feature/rate-limit", "sha": "abc123"}, "base": {"ref": "main"},
            "created_at": "2026-07-01T00:00:00Z", "updated_at": "2026-07-02T00:00:00Z",
            "merged_at": "2026-07-02T00:00:00Z" if merged else None,
            "html_url": "https://github.com/x/y/pull/42",
        }])
    )
    respx.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme").mock(
        return_value=httpx.Response(404)
    )


@pytest.mark.asyncio
@respx.mock
async def test_merged_pr_creates_real_decision_record():
    owner, repo = "octo-org", "rate-limit-repo"
    tenant_id = await _make_tenant_with_github_token("GitHub Decisions Test", owner, repo)
    _mock_github_api(owner, repo, merged=True)

    await run_tenant_ingestion_pipeline(tenant_id)

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        row = (await session.execute(
            text("SELECT decision_title, owner_id, rationale, actual_outcome, state FROM graph_decisions WHERE tenant_id = :t"),
            {"t": tenant_id},
        )).fetchone()

    assert row is not None, "A real merged PR must create a real graph_decisions row."
    assert "rate limiting" in row.decision_title
    assert "misbehaving tenant" in row.rationale, "Real rationale must come from the real PR description, not a placeholder."
    assert row.actual_outcome == "Merged"
    assert row.state == "Published"

    # owner_id is a real UUID FK into graph_entities, not the raw login string (a real
    # bug found and fixed: the column is typed uuid, so it must resolve to the same
    # real Person entity extract_graph() already created for this PR's author).
    assert row.owner_id is not None, "owner_id must resolve to a real entity, not be left NULL when the author is known."
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        owner_entity = (await session.execute(
            text("SELECT canonical_name, entity_type FROM graph_entities WHERE id = :id"), {"id": row.owner_id}
        )).fetchone()
    assert owner_entity is not None
    assert owner_entity.canonical_name == "octocat"
    assert owner_entity.entity_type == "person"


@pytest.mark.asyncio
@respx.mock
async def test_closed_unmerged_pr_records_rejected_decision():
    owner, repo = "octo-org", "rejected-repo"
    tenant_id = await _make_tenant_with_github_token("GitHub Decisions Rejected Test", owner, repo)
    _mock_github_api(owner, repo, merged=False)

    await run_tenant_ingestion_pipeline(tenant_id)

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        row = (await session.execute(
            text("SELECT actual_outcome, state FROM graph_decisions WHERE tenant_id = :t"), {"t": tenant_id}
        )).fetchone()

    assert row is not None
    assert row.actual_outcome == "Closed without merging"
    assert row.state == "Rejected"


@pytest.mark.asyncio
@respx.mock
async def test_resync_does_not_duplicate_the_decision():
    owner, repo = "octo-org", "idempotent-repo"
    tenant_id = await _make_tenant_with_github_token("GitHub Decisions Idempotency Test", owner, repo)
    _mock_github_api(owner, repo, merged=True)

    await run_tenant_ingestion_pipeline(tenant_id)
    await run_tenant_ingestion_pipeline(tenant_id)  # real resync, same PR data again

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        count = (await session.execute(
            text("SELECT COUNT(*) FROM graph_decisions WHERE tenant_id = :t"), {"t": tenant_id}
        )).scalar()

    assert count == 1, f"A resync must not create a duplicate decision record, found {count}."
