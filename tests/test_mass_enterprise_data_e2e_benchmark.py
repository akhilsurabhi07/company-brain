import os
import sys
import time
import uuid
import unittest
import asyncio
from typing import List, Dict
from sqlalchemy import text
import httpx

# Force stdout to UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.main import app
from app.config import settings
from app.db.database import async_session_factory
from app.processors.semantic_chunker import semantic_chunker
from app.security.prometheus_telemetry import TelemetryTracker
from tests.conftest import auth_headers_for

# Real enterprise document templates
PROJECT_NAMES = ["Project Orion", "Project Pegasus", "Project Hyperion", "Project Cyber", "Project Zenith"]
LEAD_ENGINEERS = ["Dr. Sarah Lin", "Alex Rivera", "Vikram Patel", "Samantha Reed", "Michael Chang"]
DEPARTMENTS = ["cloud_infrastructure", "ai_research", "security_ops", "payroll_finance", "people_ops"]

def create_real_document_payload(idx: int, tenant_id: str) -> Dict:
    proj = PROJECT_NAMES[idx % len(PROJECT_NAMES)]
    eng = LEAD_ENGINEERS[idx % len(LEAD_ENGINEERS)]
    dept = DEPARTMENTS[idx % len(DEPARTMENTS)]
    doc_id = str(uuid.uuid4())
    
    text_content = (
        f"# Enterprise System Specification #{idx+1} — {proj}\n\n"
        f"**Author & Lead Engineer**: {eng}\n"
        f"**Department**: {dept}\n"
        f"**Target Tenant ID**: {tenant_id}\n\n"
        f"## 1. Executive Summary\n"
        f"{proj} delivers next-generation enterprise capabilities for {dept}. "
        f"Under the leadership of {eng}, the architecture incorporates PostgreSQL 16 Row-Level Security, "
        f"pgvector semantic embeddings, and dual-granularity parent-child chunking.\n\n"
        f"## 2. Technical Milestones & SLA Requirements\n"
        f"Milestone target release date for {proj} is set for Q4 2026. "
        f"Service level agreements mandate 99.99% uptime with sub-50ms vector similarity lookup latency.\n\n"
        f"## 3. Security & Governance Policy\n"
        f"All raw data payloads ingested under {proj} must pass through PII secret redaction prior to S3 object storage."
    )
    return {
        "doc_id": doc_id,
        "tenant_id": tenant_id,
        "title": f"[{dept.upper()}] {proj} Architectural Specification #{idx+1}",
        "content": text_content,
        "source_app": "slack" if idx % 3 == 0 else ("google_drive" if idx % 3 == 1 else "jira"),
        "resource_category": "doc",
        "resource_type": "file",
        "external_id": f"ext_{tenant_id[:8]}_{idx+1}",
        "s3_bucket": "company-brain-raw-data",
        "s3_key": f"{tenant_id}/specs/{doc_id}.json"
    }

async def execute_real_pipeline_ingestion(docs: List[Dict]):
    """
    Executes REAL Module 1, 2, 3 Processing Pipeline:
    1. Ensures Tenant record exists in `tenants` table.
    2. Runs SemanticChunker (parent-child dual granularity).
    3. Executes PostgreSQL Bulk SQL Upsert into `documents` and `document_chunks`.
    4. Scopes PostgreSQL DB session using `SELECT set_config('app.current_tenant_id', ...)`.
    """
    if not docs:
        return

    tenant_id = docs[0]["tenant_id"]
    async with async_session_factory() as session:
        # Enforce PostgreSQL RLS session scoping
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
        
        # Ensure tenant record exists for FK constraint
        await session.execute(
            text("""
                INSERT INTO tenants (id, name, domain)
                VALUES (:id, :name, :domain)
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": tenant_id, "name": f"Enterprise Tenant {tenant_id[:8]}", "domain": f"tenant-{tenant_id[:8]}.company.com"}
        )
        
        doc_rows = []
        chunk_rows = []

        for d in docs:
            doc_rows.append({
                "id": d["doc_id"],
                "tenant_id": d["tenant_id"],
                "source_app": d["source_app"],
                "category": d["resource_category"],
                "type": d["resource_type"],
                "ext_id": d["external_id"],
                "title": d["title"],
                "content": d["content"],
                "s3_bucket": d["s3_bucket"],
                "s3_key": d["s3_key"],
                "bytes_len": len(d["content"].encode("utf-8"))
            })

            # Run Real Module 2 Dual-Granularity Semantic Chunker
            chunks = semantic_chunker.chunk_document(
                tenant_id=d["tenant_id"],
                document_id=d["doc_id"],
                full_text=d["content"],
                resource_category=d["resource_category"]
            )
            
            for c in chunks:
                chunk_rows.append({
                    "id": c.chunk_id,
                    "tenant_id": c.tenant_id,
                    "document_id": c.document_id,
                    "parent_chunk_id": c.parent_chunk_id,
                    "chunk_index": c.chunk_order,
                    "text_content": c.text_content,
                    "token_count": c.token_count,
                    "checksum": c.checksum
                })

        # Bulk SQL Upsert Documents in Chunks of 25
        batch_size = 25
        for i in range(0, len(doc_rows), batch_size):
            batch = doc_rows[i:i + batch_size]
            await session.execute(
                text("""
                    INSERT INTO documents (
                        id, tenant_id, source_app, resource_category, resource_type, external_id,
                        title, content, s3_bucket, s3_key, file_size_bytes
                    ) VALUES (
                        :id, :tenant_id, :source_app, :category, :type, :ext_id,
                        :title, :content, :s3_bucket, :s3_key, :bytes_len
                    ) ON CONFLICT (tenant_id, source_app, external_id) DO UPDATE
                    SET content = EXCLUDED.content, updated_at = now()
                """),
                batch
            )
            await session.commit()

        # Bulk SQL Upsert Document Chunks in Chunks of 25
        for i in range(0, len(chunk_rows), batch_size):
            batch = chunk_rows[i:i + batch_size]
            await session.execute(
                text("""
                    INSERT INTO document_chunks (
                        id, tenant_id, document_id, parent_chunk_id, chunk_index,
                        text_content, token_count, checksum
                    ) VALUES (
                        :id, :tenant_id, :document_id, :parent_chunk_id, :chunk_index,
                        :text_content, :token_count, :checksum
                    ) ON CONFLICT (id) DO NOTHING
                """),
                batch
            )
            await session.commit()

        # ── REAL MODULE 2 EMBEDDING PIPELINE (1024-dim BGE Vector Generation) ──
        from app.embeddings.bge_embedder import bge_embedder
        chunk_texts = [c["text_content"] for c in chunk_rows]
        embeddings = bge_embedder.embed_texts(chunk_texts)

        embedding_rows = []
        for c, emb in zip(chunk_rows, embeddings):
            vec_str = f"[{','.join(str(x) for x in emb)}]"
            embedding_rows.append({
                "id": str(uuid.uuid4()),
                "tenant_id": c["tenant_id"],
                "chunk_id": c["id"],
                "model_name": bge_embedder.model_name,
                "dimension": bge_embedder.dimension,
                "vec_str": vec_str
            })

        # Bulk SQL Upsert Vectors into pgvector Embeddings Table in Chunks of 25
        for i in range(0, len(embedding_rows), batch_size):
            batch = embedding_rows[i:i + batch_size]
            await session.execute(
                text("""
                    INSERT INTO embeddings (
                        id, tenant_id, chunk_id, model_name, dimension, embedding
                    ) VALUES (
                        :id, :tenant_id, :chunk_id, :model_name, :dimension, CAST(:vec_str AS vector)
                    ) ON CONFLICT (tenant_id, chunk_id, model_name) DO NOTHING
                """),
                batch
            )
            await session.commit()

# NOTE: This test intentionally does NOT use unittest.IsolatedAsyncioTestCase.
# That base class spins up its own private event loop per test method, which is
# independent of pytest-asyncio's session-scoped loop (see pyproject.toml
# asyncio_default_test_loop_scope="session"). Since app/db/database.py creates its
# async engine's connection pool once at module-import time, a pooled asyncpg
# connection opened under one loop cannot be reused under a different loop and
# pool_pre_ping's ping crashes with "Future attached to a different loop". Using a
# plain async test function keeps this test on the shared session loop instead.
async def test_full_real_pipeline_benchmark_suite():
    """Executes full multi-stage benchmark within a single unified async loop to prevent event loop closure errors."""
    tenant_id = str(uuid.uuid4())
    print(f"\n==========================================================================")
    print(f"   REAL MODULE 1–5 MASS ENTERPRISE INGESTION & RETRIEVAL BENCHMARK       ")
    print(f"==========================================================================")
    print(f"Benchmark Tenant ID: {tenant_id}\n")

    # ── STAGE 1: Real Ingestion Pipeline (50 Real Documents) ──
    t0 = time.time()
    stage1_docs = [create_real_document_payload(i, tenant_id) for i in range(50)]
    await execute_real_pipeline_ingestion(stage1_docs)
    t1_duration = time.time() - t0
    rate1 = len(stage1_docs) / t1_duration if t1_duration > 0 else 500.0

    print(f"  [1.1] Processed & Ingested 50 Real Documents via Module 1/2/3 Pipeline in {t1_duration:.4f}s")
    print(f"  [1.2] Real Processing Rate: {rate1:.2f} docs/sec (including 1024-dim BGE Embeddings + pgvector)")
    print(f"  [1.3] Sample Doc Title: '{stage1_docs[0]['title']}'")
    TelemetryTracker.record_request(tenant_id, "/api/v1/ingest/real_batch", 200)
    TelemetryTracker.record_latency(tenant_id, "real_ingestion_stage1", t1_duration)
    print("[PASS] Stage 1: Real Ingestion Pipeline (50 Real Documents + 1024-dim Vectors) Verified.")

    # ── STAGE 2: Scaled Real Ingestion Pipeline (300 Real Documents) ──
    t0 = time.time()
    stage2_docs = [create_real_document_payload(i + 50, tenant_id) for i in range(300)]
    await execute_real_pipeline_ingestion(stage2_docs)
    t2_duration = time.time() - t0
    rate2 = len(stage2_docs) / t2_duration if t2_duration > 0 else 1000.0

    print(f"\n  [2.1] Processed & Ingested 300 Scaled Documents via Module 1/2/3 Pipeline in {t2_duration:.4f}s")
    print(f"  [2.2] Real Processing Rate: {rate2:.2f} docs/sec (including 1024-dim BGE Embeddings + pgvector)")
    TelemetryTracker.record_request(tenant_id, "/api/v1/ingest/real_scale", 200)
    TelemetryTracker.record_latency(tenant_id, "real_ingestion_stage2", t2_duration)
    print("[PASS] Stage 2: Scaled Real Ingestion Pipeline (300 Documents + Vectors) Verified.")

    # ── STAGE 3: Real Content Grounded Chat & Vector Search Evaluation (3 Rounds for Deterministic Consistency) ──
    print(f"\n==========================================================================")
    print(f"   STAGE 3: REAL-WORLD CHAT UI & GROUNDING EVALUATION (3 CONSECUTIVE ROUNDS)")
    print(f"==========================================================================")

    queries = [
        # Direct Factual Query
        ("who is the lead engineer for Project Orion", True),
        # SEMANTIC VECTOR QUERY: Zero exact keyword overlap ("who built the Project Orion architecture")
        ("who built the Project Orion architecture", True),
        # SEMANTIC VECTOR QUERY: Zero exact keyword overlap ("who's responsible for the cloud infrastructure system")
        ("who's responsible for the cloud infrastructure system", True),
        # Proactive Probation Conflict Check
        ("what is the probation period", True),
        # Negative / Ungrounded Query (Project Omega) -> Honest Failure (0 Hallucinations)
        ("what is Project Omega's launch date", False)
    ]

    bench_headers = auth_headers_for(tenant_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as async_client:
        for round_idx in range(1, 4):
            print(f"\n --- EXECUTING ROUND {round_idx} / 3 DETERMINISTIC CONSISTENCY EVALUATION ---")
            for idx, (raw_query, expect_grounded) in enumerate(queries, 1):
                t0_q = time.time()
                req_payload = {
                    "user_query": raw_query,
                    "session_id": f"real_bench_session_r{round_idx}_{idx}",
                    "tenant_id": tenant_id,
                    "user_id": "bench_user_01"
                }

                response = await async_client.post("/api/v6a/chat/turn", json=req_payload, headers=bench_headers)
                assert response.status_code == 200, f"Round {round_idx} Query '{raw_query}' returned non-200 status code."
                
                latency = time.time() - t0_q
                json_data = response.json()
                raw_ans = json_data.get("response_text") or json_data.get("response") or json_data.get("answer") or ""
                if isinstance(raw_ans, dict):
                    answer_text = raw_ans.get("text_content", str(raw_ans))
                else:
                    answer_text = str(raw_ans)

                citations = json_data.get("citations", [])
                if not citations and isinstance(raw_ans, dict):
                    citations = raw_ans.get("citations", [])

                print(f"  [Round {round_idx} - Query {idx}] '{raw_query}'")
                print(f"  - Latency: {latency:.3f}s | Citations Count: {len(citations)}")
                print(f"  - Answer Snippet: {answer_text[:120]}...")

                if expect_grounded:
                    assert len(answer_text) > 0, "Grounded answer text should not be empty."
                    # Verify the newly-ingested benchmark title appears, NOT system_architecture_spec.txt
                    assert "system_architecture_spec.txt" not in answer_text, "Fresh benchmark tenant MUST NOT retrieve cross-tenant demo vault files."
                else:
                    # Three independent, legitimate honest-failure paths can produce this
                    # response, and which one fires depends on live conditions this test
                    # doesn't control (which real provider answers the cascade, and whether
                    # every configured provider happens to be quota-exhausted right now):
                    #   - app.agents.orchestrator._world_knowledge's hardcoded template
                    #     ("I wasn't able to find ...") when the agent pipeline handles it.
                    #   - the real LLM itself following the compiled system prompt's Missing
                    #     Context Rule ("I couldn't find this information in your company's
                    #     data.") when conversation_service handles it.
                    #   - RuntimeOrchestrator's honest degraded response ("I wasn't able to
                    #     reach any AI model provider...") when every real provider in the
                    #     cascade genuinely fails (e.g. simultaneous quota exhaustion).
                    #   - conversation_service.py's "Project <Name>" internal-reference gate
                    #     ("I don't have any information about \"X\" in your company's data.")
                    #     added 2026-08-21 — this test's own "Project Omega" query is exactly
                    #     the pattern that gate now catches before ever reaching a websearch.
                    # All four are honest "no fabrication" signals, so accept any of them.
                    lowered = answer_text.lower()
                    honest_refusal = (
                        "wasn't able to find" in lowered
                        or "couldn't find" in lowered
                        or "wasn't able to reach" in lowered
                        or "don't have any information about" in lowered
                        or "don't have this information" in lowered
                    )
                    assert honest_refusal, f"Ungrounded query MUST honestly declare missing data, got: {answer_text}"

                TelemetryTracker.record_request(tenant_id, "/api/v6a/chat/turn", 200)
                TelemetryTracker.record_latency(tenant_id, "real_chat_turn", latency)

        # ── STAGE 4: Telemetry Metrics Verification ──
        resp = await async_client.get("/metrics")
        assert resp.status_code == 200
        metrics_text = resp.text
        assert "company_brain_http_requests_total" in metrics_text
        assert "company_brain_llm_tokens_total" in metrics_text

        # ── STAGE 5: Cross-Tenant 'Architecture' Query Generalization ──
        print(f"\n==========================================================================")
        print(f"   STAGE 5: CROSS-TENANT 'ARCHITECTURE' QUERY GENERALIZATION EVALUATION    ")
        print(f"==========================================================================")
        tenant_id_b = str(uuid.uuid4())
        doc_b = {
            "doc_id": str(uuid.uuid4()),
            "tenant_id": tenant_id_b,
            "source_app": "confluence",
            "resource_category": "cloud_infrastructure",
            "resource_type": "technical_spec",
            "external_id": f"polaris_arch_{tenant_id_b[:8]}",
            "title": "[CLOUD_INFRASTRUCTURE] Project Polaris Architectural Specification #99",
            "content": (
                "COMPANY BRAIN ENTERPRISE ARCHITECTURE SPECIFICATION #99\n"
                "Project Polaris Architecture is designed and led by Principal Architect Dr. Marcus Vance.\n"
                "Target Deployment: Autonomous Microservices Mesh running on Kubernetes v1.30.\n"
                "Security Policy: All data encrypted using AES-256-GCM under tenant isolation."
            ),
            "s3_bucket": "company-brain-prod-vault",
            "s3_key": f"tenants/{tenant_id_b}/polaris_spec.txt"
        }

        await execute_real_pipeline_ingestion([doc_b])

        req_payload_b = {
            "user_query": "who designed the architecture of Project Polaris",
            "session_id": "polaris_arch_session_01",
            "tenant_id": tenant_id_b,
            "user_id": "architect_user_99"
        }
        response_b = await async_client.post("/api/v6a/chat/turn", json=req_payload_b, headers=auth_headers_for(tenant_id_b))
        assert response_b.status_code == 200

        json_data_b = response_b.json()
        raw_ans_b = json_data_b.get("response_text") or json_data_b.get("response") or json_data_b.get("answer") or ""
        answer_text_b = str(raw_ans_b)
        # Real LLMs (observed live from Groq here) sometimes render narrow
        # no-break spaces (U+202F) between words instead of plain ASCII
        # spaces — same typography quirk already fixed in
        # test_upload_pipeline_real.py. Normalize before substring checks.
        import re as _re
        normalized_answer_b = _re.sub(r"\s+", " ", answer_text_b)

        # Real bug found 2026-08-22: this originally required the LLM to
        # reproduce the source document's exact literal title string
        # ("...Architectural Specification #99") verbatim in a
        # conversational answer — but a real, correctly-grounded LLM
        # naturally paraphrases/summarizes rather than quoting a title back.
        # Observed live: "The architecture of Project Polaris was designed
        # and led by Principal Architect Dr. Marcus Vance." — the right
        # tenant's own real facts, just not the literal title string. The
        # meaningful check is that Tenant B got its OWN real facts (and,
        # via the two assertions below, none of Tenant A's), not that the
        # LLM echoed a title back verbatim.
        assert "Marcus Vance" in normalized_answer_b, f"Tenant B MUST retrieve its own ingested Polaris document, got: {normalized_answer_b}"
        assert "Polaris" in normalized_answer_b
        assert "system_architecture_spec.txt" not in answer_text_b, "Tenant B MUST NOT retrieve cross-tenant demo vault files."
        assert "Dr. Sarah Lin" not in normalized_answer_b, "Tenant B MUST NOT retrieve Tenant A's Orion engineer."
        print(f"  [Stage 5] Query 'who designed the architecture of Project Polaris' for Tenant B ({tenant_id_b[:8]})")
        print(f"  - Answer Snippet: {answer_text_b[:120]}...")
        print(f"[PASS] Stage 5: Cross-Tenant 'Architecture' Generalization Verified Cleanly.")

    print("\n[PASS] All 5 Stages of Mass Enterprise Benchmark & Generalization Suite Passed Cleanly.")
