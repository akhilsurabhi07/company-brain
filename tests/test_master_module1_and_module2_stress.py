"""
Master End-to-End Stress & Integration Test Suite — Module 1 & Module 2
========================================================================
Tests the complete multi-modal enterprise pipeline from raw byte extraction
(Module 1) through normalization, context building, parent-child chunking,
multi-dimensional scoring, embedding, pgvector storage, RLS security audit,
and hybrid similarity retrieval (Module 2) on live AWS RDS PostgreSQL.
"""
import uuid
import math
import asyncio
import pytest
from sqlalchemy import text

# Module 1 Imports
from app.extractors.composite_extractor import multimodal_extractor
from app.db.extracted_doc_repo import extracted_doc_repo

# Module 2 Imports
from app.processors.content_normalizer import content_normalizer
from app.processors.document_context_builder import document_context_builder
from app.processors.semantic_chunker import semantic_chunker
from app.processors.chunk_validator import chunk_validator
from app.embeddings.embedding_orchestrator import embedding_orchestrator
from app.db.chunk_vector_repo import chunk_vector_repo
from app.db.retrievers.retrieval_orchestrator import retrieval_orchestrator
from app.db.database import async_session_factory

@pytest.mark.asyncio
async def test_master_module1_and_module2_end_to_end_pipeline():
    """
    Unified Master Test connecting Module 1 (Multi-Modal Extraction)
    and Module 2 (Semantic Chunking & Embeddings) on live AWS RDS PostgreSQL.
    """
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    doc_a_id = str(uuid.uuid4())
    doc_b_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # STEP 1: Provision Multi-Tenant Setup in AWS RDS PostgreSQL
    # ------------------------------------------------------------------
    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant Alpha Corp', :domain)"), {"id": tenant_a, "domain": f"alpha_{tenant_a[:8]}.com"})
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant Beta Inc', :domain)"), {"id": tenant_b, "domain": f"beta_{tenant_b[:8]}.com"})

        # Tenant A Document Record
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_a}'"))
        await session.execute(text("""
            INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
            VALUES (:doc_id, :tenant_a, 'google_drive', 'doc', 'file', 'ALPHA-DOC-01', 'Alpha Multi-Modal Financial Strategy.csv', 'bucket', 'key')
        """), {"doc_id": doc_a_id, "tenant_a": tenant_a})

        # Tenant B Document Record
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_b}'"))
        await session.execute(text("""
            INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
            VALUES (:doc_id, :tenant_b, 'slack', 'chat', 'message', 'BETA-DOC-01', 'Beta Payroll & Bonuses.csv', 'bucket', 'key')
        """), {"doc_id": doc_b_id, "tenant_b": tenant_b})

        await session.commit()

    # ------------------------------------------------------------------
    # STEP 2: Module 1 Multi-Modal Extraction (Raw Bytes -> Extracted Document)
    # ------------------------------------------------------------------
    csv_bytes_alpha = (
        b"Quarter,Revenue,Growth,Strategy\n"
        b"Q1 2026,$1.4M,35.0%,Expand Enterprise Sales in Europe\n"
        b"Q2 2026,$1.9M,42.0%,Deploy BGE-Large Self-Hosted Embeddings\n"
        b"Q3 2026,$2.8M,48.0%,AWS RDS PostgreSQL pgvector HNSW Acceleration\n"
    )

    csv_bytes_beta = (
        b"Employee,Level,BaseSalary,Bonus\n"
        b"Alice,L7,$280000,$50000\n"
        b"Bob,L6,$210000,$35000\n"
    )

    # Extract Tenant Alpha Document
    extracted_doc_a = await multimodal_extractor.extract(
        tenant_id=tenant_a,
        document_id=doc_a_id,
        file_bytes=csv_bytes_alpha,
        filename="Alpha_Financial_Strategy.csv",
        mime_type="text/csv",
    )
    assert len(extracted_doc_a.tables) == 1
    assert "| Quarter | Revenue | Growth | Strategy |" in extracted_doc_a.tables[0].grid_markdown

    # Persist Module 1 Data to AWS RDS PostgreSQL
    db_id_a = await extracted_doc_repo.save_extracted_document(extracted_doc_a)
    assert db_id_a != ""

    # Extract Tenant Beta Document
    extracted_doc_b = await multimodal_extractor.extract(
        tenant_id=tenant_b,
        document_id=doc_b_id,
        file_bytes=csv_bytes_beta,
        filename="Beta_Payroll.csv",
        mime_type="text/csv",
    )
    assert len(extracted_doc_b.tables) == 1

    # Persist Module 1 Data to AWS RDS PostgreSQL
    db_id_b = await extracted_doc_repo.save_extracted_document(extracted_doc_b)
    assert db_id_b != ""

    # ------------------------------------------------------------------
    # STEP 3: Module 2 Semantic Chunking, Embeddings & Vector Storage
    # ------------------------------------------------------------------
    # Tenant Alpha Pipeline
    ctx_tree_a = document_context_builder.build_context_tree(extracted_doc_a)
    chunks_a = semantic_chunker.chunk_document(tenant_a, doc_a_id, ctx_tree_a.full_context_text)
    valid_chunks_a, _ = chunk_validator.validate_and_score_chunks(chunks_a)
    vectors_a = embedding_orchestrator.generate_embeddings_for_chunks(tenant_a, doc_a_id, valid_chunks_a)
    save_status_a = await chunk_vector_repo.save_chunks_and_embeddings(tenant_a, doc_a_id, valid_chunks_a, vectors_a)
    assert save_status_a is True

    # Tenant Beta Pipeline
    ctx_tree_b = document_context_builder.build_context_tree(extracted_doc_b)
    chunks_b = semantic_chunker.chunk_document(tenant_b, doc_b_id, ctx_tree_b.full_context_text)
    valid_chunks_b, _ = chunk_validator.validate_and_score_chunks(chunks_b)
    vectors_b = embedding_orchestrator.generate_embeddings_for_chunks(tenant_b, doc_b_id, valid_chunks_b)
    save_status_b = await chunk_vector_repo.save_chunks_and_embeddings(tenant_b, doc_b_id, valid_chunks_b, vectors_b)
    assert save_status_b is True

    # ------------------------------------------------------------------
    # STEP 4: End-to-End Multi-Tenant Security Isolation Audit
    # ------------------------------------------------------------------
    # Tenant Alpha queries asking about salary
    res_alpha = await retrieval_orchestrator.retrieve(tenant_a, "What are employee salaries and bonuses?", top_k=5)
    for r in res_alpha:
        assert "$280000" not in r.text_content
        assert r.document_title != "Beta Payroll & Bonuses.csv"

    # Tenant Beta queries asking about pgvector HNSW acceleration
    res_beta = await retrieval_orchestrator.retrieve(tenant_b, "What is our pgvector HNSW strategy?", top_k=5)
    for r in res_beta:
        assert "AWS RDS PostgreSQL pgvector" not in r.text_content
        assert r.document_title != "Alpha Multi-Modal Financial Strategy.csv"

    # ------------------------------------------------------------------
    # STEP 5: Quality Benchmarking (Recall@1, Recall@5, MRR, NDCG)
    # ------------------------------------------------------------------
    queries = [
        {"query": "What is the revenue for Q3 2026?", "expected": "$2.8M"},
        {"query": "What embeddings model is deployed in Q2 2026?", "expected": "BGE-Large"},
        {"query": "What index acceleration is used for vector search?", "expected": "HNSW"},
    ]

    reciprocal_ranks = []
    dcg_scores = []
    hits_at_1 = 0
    hits_at_5 = 0

    for q in queries:
        res_list = await retrieval_orchestrator.retrieve(tenant_a, q["query"], top_k=5)
        found_rank = 0
        for rank, res in enumerate(res_list, 1):
            if q["expected"].lower() in res.text_content.lower():
                found_rank = rank
                break

        if found_rank > 0:
            reciprocal_ranks.append(1.0 / found_rank)
            dcg_scores.append(1.0 / math.log2(found_rank + 1))
            if found_rank == 1:
                hits_at_1 += 1
            if found_rank <= 5:
                hits_at_5 += 1
        else:
            reciprocal_ranks.append(0.0)
            dcg_scores.append(0.0)

    recall_1 = hits_at_1 / len(queries)
    recall_5 = hits_at_5 / len(queries)
    mrr = sum(reciprocal_ranks) / len(queries)
    ndcg = sum(dcg_scores) / len(queries)

    print("\n======================================================================")
    print("  MODULE 1 & MODULE 2 END-TO-END QUALITY BENCHMARKS (LIVE AWS RDS)")
    print("======================================================================")
    print(f"  - Recall@1 : {recall_1 * 100:.1f}%")
    print(f"  - Recall@5 : {recall_5 * 100:.1f}%")
    print(f"  - MRR      : {mrr:.4f}")
    print(f"  - NDCG     : {ndcg:.4f}")
    print("======================================================================\n")

    assert recall_5 == 1.0
    assert mrr >= 0.75

    # ------------------------------------------------------------------
    # STEP 6: 10-Worker Concurrent Workload Across Module 1 & Module 2
    # ------------------------------------------------------------------
    async def _concurrent_e2e_task(worker_idx: int):
        d_id = str(uuid.uuid4())
        ext_id = f"WORKER_{worker_idx}_{str(uuid.uuid4())[:4]}"

        # Insert Doc
        async with async_session_factory() as session:
            await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_a}'"))
            await session.execute(text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
                VALUES (:doc_id, :tenant_id, 'slack', 'chat', 'message', :ext_id, :title, 'bucket', 'key')
            """), {"doc_id": d_id, "tenant_id": tenant_a, "ext_id": ext_id, "title": f"Worker Doc {worker_idx}"})
            await session.commit()

        # Module 1 Extraction
        raw_csv = f"Item,Qty,Notes\nWidget_{worker_idx},100,Stress test payload for worker {worker_idx}\n".encode("utf-8")
        ext = await multimodal_extractor.extract(tenant_a, d_id, raw_csv, f"w_{worker_idx}.csv", "text/csv")
        await extracted_doc_repo.save_extracted_document(ext)

        # Module 2 Chunking & Embedding
        tree = document_context_builder.build_context_tree(ext)
        c_list = semantic_chunker.chunk_document(tenant_a, d_id, tree.full_context_text)
        v_list, _ = chunk_validator.validate_and_score_chunks(c_list)
        e_list = embedding_orchestrator.generate_embeddings_for_chunks(tenant_a, d_id, v_list)
        return await chunk_vector_repo.save_chunks_and_embeddings(tenant_a, d_id, v_list, e_list)

    worker_res = await asyncio.gather(*[_concurrent_e2e_task(i) for i in range(10)])
    assert len(worker_res) == 10
    assert all(r is True for r in worker_res)
