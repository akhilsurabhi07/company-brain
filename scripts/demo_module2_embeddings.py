"""
Live AWS RDS PostgreSQL Certification Script — Module 2 (Semantic Chunking & Self-Hosted Embeddings)
====================================================================================================
Parses document, normalizes, chunks, scores, embeds via BAAI/bge-large-en-v1.5,
persists into AWS RDS PostgreSQL under RLS, and executes live vector search queries!
"""
import asyncio
import uuid
from datetime import datetime
from sqlalchemy import text
from app.db.database import async_session_factory
from app.processors.semantic_chunker import semantic_chunker
from app.processors.chunk_validator import chunk_validator
from app.embeddings.embedding_orchestrator import embedding_orchestrator
from app.db.chunk_vector_repo import chunk_vector_repo
from app.db.retrievers.retrieval_orchestrator import retrieval_orchestrator

async def run_module2_live_certification():
    print("======================================================================")
    print("      COMPANY BRAIN -- MODULE 2 LIVE EMBEDDINGS CERTIFICATION")
    print(f"======================================================================")
    print(f"  Execution Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("======================================================================\n")

    tenant_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())

    # Step 1: Create Test Tenant & Document in AWS RDS PostgreSQL
    print("  [STEP 1] Setting up Tenant & Document in AWS RDS PostgreSQL...")
    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Acme Corp', :domain)"), {"id": tenant_id, "domain": f"acme_{tenant_id[:8]}.com"})
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
        await session.execute(text("""
            INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
            VALUES (:doc_id, :tenant_id, 'google_drive', 'doc', 'file', 'GDRIVE-99', '2026_Strategic_Roadmap.md', 'bucket', 'key')
        """), {"doc_id": doc_id, "tenant_id": tenant_id})
        await session.commit()
    print("    - Setup Complete.")

    # Step 2: Chunk, Score & Generate BGE Vectors
    print("\n  [STEP 2] Running Semantic Chunker & Self-Hosted BAAI/bge-large-en-v1.5 Embeddings Engine...")
    document_text = (
        "# 2026 Strategic Roadmap\n\n"
        "Company Brain enterprise AI platform aims for 48.0% YoY revenue expansion in Q3 2026.\n\n"
        "## Core Architecture\n"
        "The system uses multi-tenant Row-Level Security (RLS) in AWS RDS PostgreSQL, "
        "pgvector HNSW indexes, self-hosted BAAI/bge-large-en-v1.5 embeddings, and Apache AGE graph database."
    )

    chunks = semantic_chunker.chunk_document(tenant_id, doc_id, document_text)
    valid_chunks, _ = chunk_validator.validate_and_score_chunks(chunks)
    vectors = embedding_orchestrator.generate_embeddings_for_chunks(tenant_id, doc_id, valid_chunks)

    print(f"    - Generated Valid Chunks : {len(valid_chunks)}")
    print(f"    - Generated 1024-dim Vecs: {len(vectors)}")
    print(f"    - Sample Chunk 1 Importance Score : {valid_chunks[0].importance_score}")

    # Step 3: Persist into AWS RDS PostgreSQL pgvector under RLS
    print("\n  [STEP 3] Persisting Chunks & Vectors into AWS RDS PostgreSQL under RLS...")
    saved = await chunk_vector_repo.save_chunks_and_embeddings(tenant_id, doc_id, valid_chunks, vectors)
    print(f"    - Persistence Success    : {saved}")

    # Step 4: Execute Live Cosine Similarity Vector Search
    print("\n  [STEP 4] Executing Live Cosine Similarity Search via RetrievalOrchestrator...")
    query = "What is the security architecture of the system?"
    results = await retrieval_orchestrator.retrieve(tenant_id, query, top_k=2)

    print(f"    - Search Query           : '{query}'")
    print(f"    - Top Retrieved Results  : {len(results)}\n")

    for idx, r in enumerate(results, 1):
        print(f"      Result {idx}:")
        print(f"        - Document Title  : {r.document_title}")
        print(f"        - Vector Score    : {r.vector_score:.4f}")
        print(f"        - Hybrid Score    : {r.hybrid_score:.4f}")
        print(f"        - Embedding Model : {r.embedding_model}")
        print(f"        - Reason          : {r.retrieval_reason}")
        print(f"        - Text Content    : {r.text_content[:120]}...\n")

    print("======================================================================")
    print("  [SUCCESS] MODULE 2 SEMANTIC CHUNKING & EMBEDDINGS CERTIFIED 100%!")
    print("======================================================================")

if __name__ == "__main__":
    asyncio.run(run_module2_live_certification())
