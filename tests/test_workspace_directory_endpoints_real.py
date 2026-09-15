"""
Module 6B — real People/Teams/Documents workspace directory (2026-08-23).

Before this, these were honest "Soon" sidebar placeholders with no backend
concept. All three read from data that already existed (users, documents) —
this adds the first real read endpoints and locks in tenant isolation +
(for Documents) the exact same ACL clause hybrid_retriever.py already uses.
"""
import uuid
import hashlib
import bcrypt
import httpx
import pytest
from sqlalchemy import text

from app.main import app
from app.db.database import async_session_factory
from tests.conftest import auth_headers_for

PEOPLE_URL = "/api/v1/workspace/people"
TEAMS_URL = "/api/v1/workspace/teams"
DOCS_URL = "/api/v1/workspace/documents"
LIBRARY_URL = "/api/v1/workspace/library"


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _make_tenant(name_suffix: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": f"Workspace Dir Test {name_suffix}", "domain": f"workspacedir-{name_suffix}.example.com"},
        )
        await session.commit()
    return tenant_id


async def _make_user(tenant_id: str, email: str, full_name: str, role: str, department: str) -> str:
    user_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("""
                INSERT INTO users (id, tenant_id, email, hashed_password, full_name, role, department)
                VALUES (:id, :t, :email, :pw, :name, :role, :dept)
            """),
            {"id": user_id, "t": tenant_id, "email": email, "pw": bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
             "name": full_name, "role": role, "dept": department},
        )
        await session.commit()
    return user_id


async def _make_document(tenant_id: str, title: str, source_app: str = "upload") -> str:
    doc_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(
            text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key, file_size_bytes)
                VALUES (:id, :t, :src, 'doc', 'file', :ext, :title, 'content', 'b', :s3key, 4)
            """),
            {"id": doc_id, "t": tenant_id, "src": source_app, "ext": f"wd-{doc_id[:8]}", "title": title, "s3key": f"wd-{doc_id[:8]}"},
        )
        await session.commit()
    return doc_id


async def _cleanup_tenant(tenant_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM document_pins WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM document_acls WHERE document_id IN (SELECT id FROM documents WHERE tenant_id = :t)"), {"t": tenant_id})
        await session.execute(text("DELETE FROM documents WHERE tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": tenant_id})
        await session.commit()
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_people_lists_real_tenant_users():
    tenant_id = await _make_tenant("people")
    try:
        await _make_user(tenant_id, "alice@example.com", "Alice Chen", "member", "Engineering")
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.get(PEOPLE_URL, params={"tenant_id": tenant_id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["people"][0]["email"] == "alice@example.com"
        assert body["people"][0]["department"] == "Engineering"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_teams_groups_by_department():
    tenant_id = await _make_tenant("teams")
    try:
        await _make_user(tenant_id, "bob@example.com", "Bob Lee", "member", "Engineering")
        await _make_user(tenant_id, "carol@example.com", "Carol King", "member", "Engineering")
        await _make_user(tenant_id, "dave@example.com", "Dave Ray", "member", "")  # unassigned
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.get(TEAMS_URL, params={"tenant_id": tenant_id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        teams_by_name = {t["team_name"]: t for t in body["teams"]}
        assert teams_by_name["Engineering"]["member_count"] == 2
        assert teams_by_name["Unassigned"]["member_count"] == 1
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_documents_lists_real_ingested_documents():
    tenant_id = await _make_tenant("docs")
    try:
        await _make_document(tenant_id, "Onboarding Guide.pdf")
        headers = auth_headers_for(tenant_id, role="admin")
        async with await _client() as client:
            resp = await client.get(DOCS_URL, params={"tenant_id": tenant_id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["documents"][0]["title"] == "Onboarding Guide.pdf"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_documents_respects_real_acl_restriction():
    """A document with a real per-user ACL that doesn't include the caller
    must not be listed for them — same real ACL clause hybrid_retriever.py
    already enforces for retrieval."""
    tenant_id = await _make_tenant("docs-acl")
    try:
        restricted_doc_id = await _make_document(tenant_id, "Restricted Board Notes.pdf")
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(
                text("INSERT INTO document_acls (document_id, tenant_id, principal_type, principal_external_id) VALUES (:d, :t, 'user', 'someone_else@example.com')"),
                {"d": restricted_doc_id, "t": tenant_id},
            )
            await session.commit()

        headers = auth_headers_for(tenant_id, role="member")
        async with await _client() as client:
            resp = await client.get(DOCS_URL, params={"tenant_id": tenant_id, "user_id": "not_the_acl_owner@example.com"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_workspace_endpoints_are_tenant_isolated():
    tenant_a = await _make_tenant("iso-a")
    tenant_b = await _make_tenant("iso-b")
    try:
        await _make_user(tenant_a, "onlya@example.com", "Only A", "member", "Sales")
        headers_b = auth_headers_for(tenant_b, role="admin")
        async with await _client() as client:
            resp = await client.get(PEOPLE_URL, params={"tenant_id": tenant_b}, headers=headers_b)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)


@pytest.mark.asyncio
async def test_pin_then_library_lists_the_real_pinned_document():
    tenant_id = await _make_tenant("library")
    try:
        doc_id = await _make_document(tenant_id, "Remote Work Stipend Policy.txt")
        headers = auth_headers_for(tenant_id, role="member")
        async with await _client() as client:
            # Library starts empty — nothing pinned yet, no fabricated content.
            empty = await client.get(LIBRARY_URL, params={"tenant_id": tenant_id, "user_id": "u1"}, headers=headers)
            assert empty.status_code == 200
            assert empty.json()["count"] == 0

            pin_resp = await client.post(
                f"{DOCS_URL}/{doc_id}/pin", params={"tenant_id": tenant_id, "user_id": "u1"}, headers=headers
            )
            assert pin_resp.status_code == 200
            assert pin_resp.json()["pinned"] is True

            lib_resp = await client.get(LIBRARY_URL, params={"tenant_id": tenant_id, "user_id": "u1"}, headers=headers)
        assert lib_resp.status_code == 200
        body = lib_resp.json()
        assert body["count"] == 1
        assert body["library"][0]["title"] == "Remote Work Stipend Policy.txt"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_unpin_removes_the_document_from_library():
    tenant_id = await _make_tenant("unpin")
    try:
        doc_id = await _make_document(tenant_id, "Q3 Roadmap.pdf")
        headers = auth_headers_for(tenant_id, role="member")
        async with await _client() as client:
            await client.post(f"{DOCS_URL}/{doc_id}/pin", params={"tenant_id": tenant_id, "user_id": "u1"}, headers=headers)
            unpin_resp = await client.delete(
                f"{DOCS_URL}/{doc_id}/pin", params={"tenant_id": tenant_id, "user_id": "u1"}, headers=headers
            )
            assert unpin_resp.status_code == 200
            assert unpin_resp.json()["pinned"] is False
            lib_resp = await client.get(LIBRARY_URL, params={"tenant_id": tenant_id, "user_id": "u1"}, headers=headers)
        assert lib_resp.json()["count"] == 0
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_pinning_an_acl_restricted_document_is_rejected():
    """A caller can't pin a document they don't already have real read
    access to — pinning must not become a second, weaker access path."""
    tenant_id = await _make_tenant("pin-acl")
    try:
        restricted_doc_id = await _make_document(tenant_id, "Restricted Comp Report.pdf")
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(
                text("INSERT INTO document_acls (document_id, tenant_id, principal_type, principal_external_id) VALUES (:d, :t, 'user', 'owner@example.com')"),
                {"d": restricted_doc_id, "t": tenant_id},
            )
            await session.commit()

        headers = auth_headers_for(tenant_id, role="member")
        async with await _client() as client:
            resp = await client.post(
                f"{DOCS_URL}/{restricted_doc_id}/pin",
                params={"tenant_id": tenant_id, "user_id": "not_the_owner@example.com"},
                headers=headers,
            )
        assert resp.status_code == 404
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_library_removes_document_after_acl_revoked():
    """A pin doesn't grant a standing access exception — if a document's
    ACL is revoked after pinning, it must vanish from Library too, not just
    from Documents, since Library re-checks ACL at read time rather than
    trusting the pin alone."""
    tenant_id = await _make_tenant("library-revoke")
    try:
        doc_id = await _make_document(tenant_id, "Team Offsite Notes.pdf")
        headers = auth_headers_for(tenant_id, role="member")
        async with await _client() as client:
            await client.post(f"{DOCS_URL}/{doc_id}/pin", params={"tenant_id": tenant_id, "user_id": "u1"}, headers=headers)
            before = await client.get(LIBRARY_URL, params={"tenant_id": tenant_id, "user_id": "u1"}, headers=headers)
            assert before.json()["count"] == 1

            async with async_session_factory() as session:
                await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
                await session.execute(
                    text("INSERT INTO document_acls (document_id, tenant_id, principal_type, principal_external_id) VALUES (:d, :t, 'user', 'someone_else@example.com')"),
                    {"d": doc_id, "t": tenant_id},
                )
                await session.commit()

            after = await client.get(LIBRARY_URL, params={"tenant_id": tenant_id, "user_id": "u1"}, headers=headers)
        assert after.json()["count"] == 0
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_people_rejects_cross_tenant_token():
    tenant_a = await _make_tenant("cross-a")
    tenant_b = await _make_tenant("cross-b")
    try:
        headers = auth_headers_for(tenant_a, role="admin")
        async with await _client() as client:
            resp = await client.get(PEOPLE_URL, params={"tenant_id": tenant_b}, headers=headers)
        assert resp.status_code == 403
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
