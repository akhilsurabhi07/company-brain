"""Real end-to-end test for the browser upload ingestion path.

Regression test for a real bug found 2026-08-20: /api/v1/upload/document inserted into
documents(text_content, embedding) columns that don't exist on that table (chunks/vectors
belong on document_chunks/embeddings) — every real upload threw a 500. Fixed to use the
same real storage + chunk/embed/store pipeline as connector ingestion
(app/processors/ingestion_pipeline.py), and this test proves the whole path actually
works: upload -> real chunking -> real BGE embedding -> real Postgres persistence ->
retrievable by chat, scoped to the uploading tenant.
"""
import uuid
import httpx
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.main import app
from tests.conftest import auth_headers_for


@pytest.mark.asyncio
async def test_upload_document_is_real_and_retrievable_in_chat():
    tenant_id = str(uuid.uuid4())

    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": "Upload Test Tenant", "domain": f"upload-test-{tenant_id[:8]}.company.com"},
        )
        await session.commit()

    file_content = (
        b"COMPANY BRAIN TEST DOCUMENT.\n\n"
        b"Project Zephyr is a real-time fraud detection system led by Principal Engineer Wei Zhang.\n"
        b"It processes 40,000 transactions per second using a streaming architecture on Apache Flink.\n"
        b"The security review was completed in March 2026 by the compliance team.\n"
    )

    headers = auth_headers_for(tenant_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/upload/document",
            files={"file": ("zephyr_spec.txt", file_content, "text/plain")},
            data={"tenant_id": tenant_id, "source_label": "UPLOAD"},
            headers=headers,
        )
        assert resp.status_code == 200, f"Upload MUST succeed against the real schema, got: {resp.text}"

        body = resp.json()
        assert body["status"] == "success"
        assert body["chunks_ingested"] > 0, "Upload MUST produce at least one real chunk."
        assert body["vectors_stored"] == body["chunks_ingested"], "Every stored chunk MUST have a matching vector."

        # Confirm the chunks/vectors genuinely landed in the real tables (not just a
        # 200 response) — directly verifies against document_chunks/embeddings.
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            chunk_count = (await session.execute(
                text("SELECT COUNT(*) FROM document_chunks WHERE tenant_id = :tid"), {"tid": tenant_id}
            )).scalar()
            vector_count = (await session.execute(
                text("SELECT COUNT(*) FROM embeddings WHERE tenant_id = :tid"), {"tid": tenant_id}
            )).scalar()
            assert chunk_count == body["chunks_ingested"]
            assert vector_count == body["vectors_stored"]

        # Confirm it's actually retrievable and answerable via the real chat pipeline.
        chat_resp = await client.post("/api/v6a/chat/turn", json={
            "user_query": "who leads Project Zephyr and what does it do",
            "session_id": "upload_pipeline_test_session",
            "tenant_id": tenant_id,
            "user_id": "upload_test_user",
        }, headers=headers)
        assert chat_resp.status_code == 200
        cj = chat_resp.json()
        raw_ans = cj.get("response_text") or cj.get("response") or ""
        answer_text = str(raw_ans.get("text_content", raw_ans) if isinstance(raw_ans, dict) else raw_ans)
        # Real flake found 2026-08-21: some providers typeset names with a narrow
        # no-break space (U+202F) instead of a plain space (e.g. "Wei Zhang")
        # — real typographic formatting, not a missing fact. Normalize whitespace
        # before checking, same fix already applied in test_rbac_content_filtering_real.py.
        import re as _re
        normalized_answer = _re.sub(r"\s+", " ", answer_text)
        assert "Wei Zhang" in normalized_answer, "Chat MUST retrieve the real fact from the uploaded document."


@pytest.mark.asyncio
async def test_stats_recent_documents_created_at_is_real_iso8601():
    """Real bug found via live Admin Dashboard testing 2026-08-23: this field
    used plain Python str(datetime) ("2026-08-23 21:41:07+00:00" — a space
    where 'T' belongs), which JavaScript's Date constructor cannot reliably
    parse — every real document in the dashboard's "Recently Ingested
    Documents" list showed "Invalid Date" in the browser. Fixed to
    .isoformat(). Asserts the real ISO-8601 'T' separator directly rather than
    round-tripping through Python's own datetime parser, which is lenient
    enough to accept both forms and wouldn't actually catch this regression."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": "Stats Date Test", "domain": f"stats-date-{tenant_id[:8]}.company.com"},
        )
        await session.commit()
    headers = auth_headers_for(tenant_id)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            up = await client.post(
                "/api/v1/upload/document",
                files={"file": ("date_check.txt", b"Real short document for a date-format check.", "text/plain")},
                data={"tenant_id": tenant_id, "source_label": "UPLOAD"},
                headers=headers,
            )
            assert up.status_code == 200

            stats = await client.get("/api/v1/upload/stats", params={"tenant_id": tenant_id}, headers=headers)
            assert stats.status_code == 200
            recent = stats.json()["recent_documents"]
        assert len(recent) == 1
        created_at = recent[0]["created_at"]
        assert "T" in created_at, (
            f"created_at must be real ISO-8601 (with a 'T' date/time separator) for the "
            f"browser's Date constructor to parse — got: {created_at!r}"
        )
        assert " " not in created_at, f"created_at must not contain the old space-separated str(datetime) form: {created_at!r}"
    finally:
        async with async_session_factory() as session:
            await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
            await session.commit()


@pytest.mark.asyncio
async def test_upload_writes_a_real_ingestion_audit_log_row():
    """Real gap found 2026-08-23: this endpoint — the one every real browser
    upload actually goes through — never wrote to any audit table, so the new
    Admin Dashboard activity log would have stayed honestly-empty forever for
    every real tenant. Fixed with a real write into ingestion_audit_logs
    right after a successful upload; this proves it actually lands."""
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": "Audit Upload Test", "domain": f"audit-upload-{tenant_id[:8]}.company.com"},
        )
        await session.commit()

    headers = auth_headers_for(tenant_id)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/upload/document",
                files={"file": ("audit_check.txt", b"A short real test document for audit logging.", "text/plain")},
                data={"tenant_id": tenant_id, "source_label": "UPLOAD"},
                headers=headers,
            )
            assert resp.status_code == 200

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            row = (await session.execute(
                text("SELECT source_app, action, items_processed FROM ingestion_audit_logs WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )).fetchone()
        assert row is not None, "A real upload MUST leave a real audit log row."
        assert row.action == "document_upload"
        assert row.items_processed > 0
    finally:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            await session.execute(text("DELETE FROM ingestion_audit_logs WHERE tenant_id = :tid"), {"tid": tenant_id})
            await session.commit()
        async with async_session_factory() as session:
            await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
            await session.commit()
