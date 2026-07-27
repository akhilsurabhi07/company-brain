"""
Module 2 Test Suite — Semantic Chunking & Embeddings
=====================================================
Tests:
  1. Content Normalizer & UTF-8 / Markdown grid clean
  2. Document Context Builder tree assembly
  3. Parent-Child Dual-Granularity Semantic Chunker (500/50 & Parent 1500)
  4. Multi-Dimensional Chunk Scoring (Structural, Semantic, Business, Importance)
  5. BAAI/bge-large-en-v1.5 1024-dim embedding generation & Vector Validation
  6. Tenant-Scoped Embedding Cache lookup & isolation
  7. Consolidated Master Database Test (pgvector persistence, RLS security isolation, Recall@5/MRR/NDCG benchmarks, & 10-worker concurrency)
"""
import uuid
import math
import asyncio
import pytest
from sqlalchemy import text
from app.domain.models import ExtractedDocument, ExtractedTable
from app.processors.content_normalizer import content_normalizer
from app.processors.document_context_builder import document_context_builder
from app.processors.semantic_chunker import semantic_chunker
from app.processors.chunk_validator import chunk_validator
from app.embeddings.bge_embedder import bge_embedder
from app.embeddings.embedding_validator import embedding_validator
from app.embeddings.embedding_cache import tenant_embedding_cache
from app.embeddings.embedding_orchestrator import embedding_orchestrator
from app.db.chunk_vector_repo import chunk_vector_repo
from app.db.retrievers.retrieval_orchestrator import retrieval_orchestrator
from app.db.database import async_session_factory

@pytest.mark.asyncio
async def test_1_content_normalizer():
    """Verify UTF-8 clean, bullet unification, and whitespace normalization."""
    raw = "* Item 1\n- Item 2\n+ Item 3\n\n\n\nFinal paragraph."
    cleaned = content_normalizer.normalize_text(raw)
    assert "• Item 1" in cleaned
    assert "• Item 2" in cleaned
    assert "• Item 3" in cleaned
    assert "\n\n\n" not in cleaned

@pytest.mark.asyncio
async def test_2_document_context_builder():
    """Verify assembling ExtractedDocument into structured DocumentContextTree."""
    doc = ExtractedDocument(
        tenant_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        clean_text="# Executive Summary\nRevenue target is 40% YoY growth.",
        sections=[],
        tables=[
            ExtractedTable(
                table_id="tbl_1",
                page_number=1,
                grid_markdown="| Quarter | Revenue |\n| --- | --- |\n| Q1 | $1.4M |",
                data_json=[{"Quarter": "Q1", "Revenue": "$1.4M"}]
            )
        ],
        images=[],
        source="doc.pdf",
        checksum="mock_checksum_hash_123",
    )

    tree = document_context_builder.build_context_tree(doc)
    assert tree.document_id == doc.document_id
    assert len(tree.elements) >= 2
    assert "| Quarter | Revenue |" in tree.full_context_text

@pytest.mark.asyncio
async def test_3_parent_child_semantic_chunker():
    """Verify dual-granularity parent-child semantic chunking."""
    tenant_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    sample_text = ("# Financial Report 2026\n\nCompany Brain has achieved 48% YoY growth in Q3 2026.\n\n" * 30)

    chunks = semantic_chunker.chunk_document(tenant_id, doc_id, sample_text, resource_category="document")
    assert len(chunks) >= 2

    parent_chunks = [c for c in chunks if c.parent_chunk_id is None]
    child_chunks = [c for c in chunks if c.parent_chunk_id is not None]

    assert len(parent_chunks) >= 1
    assert len(child_chunks) >= 1
    assert child_chunks[0].parent_chunk_id == parent_chunks[0].chunk_id

@pytest.mark.asyncio
async def test_4_multi_dimensional_chunk_scoring():
    """Verify structural, semantic, business, and importance scores calculation."""
    tenant_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    sample_text = "# Executive Revenue Report\n\nRevenue for Q3 2026 reached $2,200,000 with 48.0% growth.\n\n| Region | Revenue |\n| --- | --- |\n| Global | $2.2M |"

    chunks = semantic_chunker.chunk_document(tenant_id, doc_id, sample_text)
    valid_chunks, _ = chunk_validator.validate_and_score_chunks(chunks)

    assert len(valid_chunks) > 0
    first_chunk = valid_chunks[0]
    assert 0.0 <= first_chunk.structural_score <= 1.0
    assert 0.0 <= first_chunk.semantic_score <= 1.0
    assert 0.0 <= first_chunk.business_score <= 1.0
    assert 0.0 <= first_chunk.importance_score <= 1.0

@pytest.mark.asyncio
async def test_5_bge_embedding_generation_and_validation():
    """Verify BAAI/bge-large-en-v1.5 embedding generation and vector validation."""
    texts = ["Company Brain enterprise AI platform", "Financial revenue growth Q3"]
    vectors = bge_embedder.embed_texts(texts)

    assert len(vectors) == 2
    assert len(vectors[0]) == 1024

    valid_vectors, reasons = embedding_validator.validate_batch(vectors, expected_dimension=1024)
    assert len(valid_vectors) == 2
    assert len(reasons) == 0

@pytest.mark.asyncio
async def test_6_tenant_scoped_embedding_cache():
    """Verify tenant isolation in embedding deduplication cache."""
    t1 = str(uuid.uuid4())
    t2 = str(uuid.uuid4())
    checksum = "mock_hash_12345"
    vec = [0.1] * 1024

    tenant_embedding_cache.set(t1, checksum, "BAAI/bge-large-en-v1.5", vec)

    assert tenant_embedding_cache.get(t1, checksum, "BAAI/bge-large-en-v1.5") == vec
    assert tenant_embedding_cache.get(t2, checksum, "BAAI/bge-large-en-v1.5") is None

@pytest.mark.asyncio
async def test_7_aws_rds_pgvector_persistence_and_complex_stress_audit():
    """
    Consolidated Master Database Test:
      1. Multilingual & Parent-Child Chunk Hierarchy
      2. Multi-Tenant RLS Security Isolation Audit
      3. Retrieval Quality Benchmarks (Recall@1, Recall@5, MRR, NDCG)
      4. 10-Worker Concurrent Workload Persistence
    """
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    doc_a_id = str(uuid.uuid4())
    doc_b_id = str(uuid.uuid4())

    # STEP 1: Multi-Tenant Setup in AWS RDS PostgreSQL
    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant Alpha', :domain)"), {"id": tenant_a, "domain": f"alpha_{tenant_a[:8]}.com"})
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Tenant Beta', :domain)"), {"id": tenant_b, "domain": f"beta_{tenant_b[:8]}.com"})

        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_a}'"))
        await session.execute(text("""
            INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
            VALUES (:doc_id, :tenant_a, 'google_drive', 'doc', 'file', 'ALPHA-001', 'Alpha Confidential Tech Policy.md', 'bucket', 'key')
        """), {"doc_id": doc_a_id, "tenant_a": tenant_a})

        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_b}'"))
        await session.execute(text("""
            INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
            VALUES (:doc_id, :tenant_b, 'slack', 'chat', 'message', 'BETA-001', 'Beta Internal Compensation.md', 'bucket', 'key')
        """), {"doc_id": doc_b_id, "tenant_b": tenant_b})

        await session.commit()

    # STEP 2: Complex Multilingual & Technical Ingestion
    corpus_alpha = (
        "# Executive Architecture Policy\n"
        "Company Brain uses AWS RDS PostgreSQL with Row-Level Security (RLS) and pgvector HNSW indexing.\n"
        "All database secrets and API tokens are encrypted with AES-256-GCM envelope encryption.\n\n"
        "# Technical Infrastructure & Scaling\n"
        "The system processes multi-modal PDF, Word, and Excel files into 1024-dimensional BGE-Large vectors.\n"
        "Self-hosted model inference delivers sub-10ms similarity search latencies.\n\n"
        "# Multi-Language Support\n"
        "El sistema soporta múltiples idiomas incluyendo español, alemán y japonés para empresas globales.\n"
        "Die Plattform bietet automatische Spracherkennung und granulare Mandantentrennung."
    )

    corpus_beta = (
        "# Beta Internal Compensation & Salary Structure\n"
        "Executive base salaries for Level 7 Engineers are capped at $280,000 USD per annum.\n"
        "All stock option allocations vest over a 4-year schedule with a 1-year cliff."
    )

    chunks_a = semantic_chunker.chunk_document(tenant_a, doc_a_id, corpus_alpha)
    valid_chunks_a, _ = chunk_validator.validate_and_score_chunks(chunks_a)
    vectors_a = embedding_orchestrator.generate_embeddings_for_chunks(tenant_a, doc_a_id, valid_chunks_a)
    await chunk_vector_repo.save_chunks_and_embeddings(tenant_a, doc_a_id, valid_chunks_a, vectors_a)

    chunks_b = semantic_chunker.chunk_document(tenant_b, doc_b_id, corpus_beta)
    valid_chunks_b, _ = chunk_validator.validate_and_score_chunks(chunks_b)
    vectors_b = embedding_orchestrator.generate_embeddings_for_chunks(tenant_b, doc_b_id, valid_chunks_b)
    await chunk_vector_repo.save_chunks_and_embeddings(tenant_b, doc_b_id, valid_chunks_b, vectors_b)

    # STEP 3: Rigorous Multi-Tenant RLS Security Audit
    results_alpha_query_beta_info = await retrieval_orchestrator.retrieve(tenant_a, "What are the executive salaries?", top_k=5)
    for r in results_alpha_query_beta_info:
        assert "salary" not in r.text_content.lower()
        assert r.document_title != "Beta Internal Compensation.md"

    results_beta_query_alpha_info = await retrieval_orchestrator.retrieve(tenant_b, "How are API keys encrypted?", top_k=5)
    for r in results_beta_query_alpha_info:
        assert "aes-256-gcm" not in r.text_content.lower()
        assert r.document_title != "Alpha Confidential Tech Policy.md"

    # STEP 4: Golden Evaluation Benchmarks (Recall@1, Recall@5, MRR, NDCG)
    eval_benchmark_queries = [
        {"query": "How are secrets encrypted in the database?", "expected_term": "AES-256-GCM"},
        {"query": "What vector dimension does BGE-Large use?", "expected_term": "1024-dimensional"},
        {"query": "What security mechanism provides tenant isolation?", "expected_term": "Row-Level Security"},
        {"query": "El sistema soporta múltiples idiomas?", "expected_term": "español"},
    ]

    reciprocal_ranks = []
    dcg_scores = []
    hits_at_1 = 0
    hits_at_5 = 0

    for q in eval_benchmark_queries:
        res_list = await retrieval_orchestrator.retrieve(tenant_a, q["query"], top_k=5)
        rank_found = 0

        for rank, res in enumerate(res_list, 1):
            if q["expected_term"].lower() in res.text_content.lower():
                rank_found = rank
                break

        if rank_found > 0:
            reciprocal_ranks.append(1.0 / rank_found)
            dcg_scores.append(1.0 / math.log2(rank_found + 1))
            if rank_found == 1:
                hits_at_1 += 1
            if rank_found <= 5:
                hits_at_5 += 1
        else:
            reciprocal_ranks.append(0.0)
            dcg_scores.append(0.0)

    recall_at_1 = hits_at_1 / len(eval_benchmark_queries)
    recall_at_5 = hits_at_5 / len(eval_benchmark_queries)
    mrr = sum(reciprocal_ranks) / len(eval_benchmark_queries)
    ndcg = sum(dcg_scores) / len(eval_benchmark_queries)

    print("\n======================================================================")
    print("      RETRIEVAL QUALITY BENCHMARK METRICS (LIVE AWS RDS)")
    print("======================================================================")
    print(f"  - Recall@1 : {recall_at_1 * 100:.1f}%")
    print(f"  - Recall@5 : {recall_at_5 * 100:.1f}%")
    print(f"  - MRR      : {mrr:.4f}")
    print(f"  - NDCG     : {ndcg:.4f}")
    print("======================================================================\n")

    assert recall_at_5 == 1.0
    assert mrr >= 0.75

    # STEP 5: 10-Worker Concurrent Workload Persistence
    async def _worker_task(idx: int):
        d_id = str(uuid.uuid4())
        async with async_session_factory() as session:
            await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_a}'"))
            await session.execute(text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
                VALUES (:doc_id, :tenant_id, 'slack', 'chat', 'message', :ext_id, :title, 'bucket', 'key')
            """), {"doc_id": d_id, "tenant_id": tenant_a, "ext_id": f"STRESS_{idx}_{str(uuid.uuid4())[:4]}", "title": f"Stress Doc {idx}"})
            await session.commit()

        txt = f"# Stress Document {idx}\nPerformance test chunk content for concurrent worker {idx}."
        c_list = semantic_chunker.chunk_document(tenant_a, d_id, txt)
        v_list, _ = chunk_validator.validate_and_score_chunks(c_list)
        e_list = embedding_orchestrator.generate_embeddings_for_chunks(tenant_a, d_id, v_list)
        return await chunk_vector_repo.save_chunks_and_embeddings(tenant_a, d_id, v_list, e_list)

    worker_results = await asyncio.gather(*[_worker_task(i) for i in range(10)])
    assert len(worker_results) == 10
    assert all(r is True for r in worker_results)
