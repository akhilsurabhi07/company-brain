"""
Verification script demonstrating end-to-end integration and connection
across Modules 1, 2, 3, 4, and 5 in the Enterprise Knowledge Graph & GraphRAG Platform.
"""
import os
import sys

# Ensure root workspace path is in sys.path for IDE linter and direct execution
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from typing import Dict, Any

# Module 1 Imports
from app.security.crypto import TokenEncryptor
from app.processors.pii_redactor import PIIRedactor
from app.extractors.composite_extractor import CompositeExtractor

# Module 2 Imports
from app.processors.content_normalizer import ContentNormalizer
from app.processors.semantic_chunker import SemanticChunker
from app.embeddings.bge_embedder import BGEEmbedder
from app.db.chunk_vector_repo import PostgresVectorRepo

# Module 3 Imports
from app.graph.extraction.hybrid_extractor import HybridGraphExtractor
from app.graph.validation.entity_resolver import EntityResolver
from app.graph.validation.trust_engine import TrustEngine
from app.db.postgres_graph_repo import PostgresGraphRepo

# Module 4 Imports
from app.retrieval.query_planner import QueryPlanner
from app.retrieval.graph_traversal import GraphTraversalRetriever
from app.retrieval.fusion_orchestrator import FusionOrchestrator

# Module 5 Imports
from app.gateway.policy_engine import ABACPolicyEngine
from app.gateway.query_normalizer import DirtyQueryNormalizer
from app.gateway.response_transformer import MultiFormatTransformer


def verify_m1_to_m5_connection():
    print("=" * 70)
    print("STARTING E2E MODULE 1 -> MODULE 5 PIPELINE INTEGRATION CHECK")
    print("=" * 70)

    tenant_id = "tenant_enterprise_alpha"
    user_clearance = "SECRET"

    # -------------------------------------------------------------
    # STEP 1: MODULE 1 - Security, Redaction & Extraction
    # -------------------------------------------------------------
    print("\n[Step 1] Testing Module 1: Ingestion, Redaction & Security...")
    encryptor = TokenEncryptor(secret_key="00000000000000000000000000000000")
    encrypted_token = encryptor.encrypt("ghp_secret_github_token_12345")
    decrypted_token = encryptor.decrypt(encrypted_token)
    assert decrypted_token == "ghp_secret_github_token_12345"

    redactor = PIIRedactor()
    raw_doc = "Project Phoenix leads development of QuantumEngine. AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY. Contact dev@company.com."
    sanitized_doc = redactor.redact_text(raw_doc)
    assert "[REDACTED_AWS_SECRET]" in sanitized_doc
    print("  ✓ Module 1 Token Encryption & PII/Secret Redaction Passed.")

    # -------------------------------------------------------------
    # STEP 2: MODULE 2 - Chunking, Embedding & Vector Store
    # -------------------------------------------------------------
    print("\n[Step 2] Testing Module 2: Normalization, Chunking & Vector DB...")
    normalizer = ContentNormalizer()
    normalized_doc = normalizer.normalize(sanitized_doc)

    chunker = SemanticChunker(max_chunk_size=150, overlap=20)
    chunks = chunker.chunk_document(doc_id="doc_001", text=normalized_doc, metadata={"tenant_id": tenant_id})
    assert len(chunks) > 0

    embedder = BGEEmbedder(vector_dim=384)
    chunk_vectors = [embedder.embed_text(c.text) for c in chunks]
    assert len(chunk_vectors) == len(chunks)

    vector_repo = PostgresVectorRepo()
    for idx, c in enumerate(chunks):
        vector_repo.upsert_chunk(
            chunk_id=f"c_{idx}",
            tenant_id=tenant_id,
            doc_id="doc_001",
            text=c.text,
            vector=chunk_vectors[idx]
        )
    stored_chunks = vector_repo.search_similar(tenant_id=tenant_id, query_vector=chunk_vectors[0], top_k=2)
    assert len(stored_chunks) > 0
    print("  ✓ Module 2 Chunking, BGE Embedding & Vector Storage Passed.")

    # -------------------------------------------------------------
    # STEP 3: MODULE 3 - Knowledge Graph, Entity Resolution & Trust
    # -------------------------------------------------------------
    print("\n[Step 3] Testing Module 3: Knowledge Graph, Entities & Trust...")
    graph_extractor = HybridGraphExtractor()
    extracted_graph = graph_extractor.extract_graph(doc_text=normalized_doc, doc_id="doc_001")

    resolver = EntityResolver()
    resolved_graph = resolver.resolve_and_merge(extracted_graph)

    trust_engine = TrustEngine()
    trusted_graph = trust_engine.evaluate_trust(resolved_graph)

    graph_repo = PostgresGraphRepo()
    graph_repo.upsert_graph(tenant_id=tenant_id, graph_data=trusted_graph)
    graph_facts = graph_repo.get_tenant_subgraph(tenant_id=tenant_id)
    assert len(graph_facts.get("nodes", [])) > 0
    print("  ✓ Module 3 Knowledge Graph Construction & Trust Validation Passed.")

    # -------------------------------------------------------------
    # STEP 4: MODULE 4 - GraphRAG Query Planning, Traversal & Fusion
    # -------------------------------------------------------------
    print("\n[Step 4] Testing Module 4: GraphRAG Query Planning & Fusion...")
    planner = QueryPlanner()
    raw_query = "Who leads Projct Phœnix development?"
    plan = planner.create_plan(query=raw_query, tenant_id=tenant_id)
    assert plan is not None

    query_vector = embedder.embed_text(raw_query)
    vector_results = vector_repo.search_similar(tenant_id=tenant_id, query_vector=query_vector, top_k=3)

    graph_retriever = GraphTraversalRetriever(graph_repo=graph_repo)
    graph_results = graph_retriever.traverse(tenant_id=tenant_id, seed_entities=["Project Phoenix"], max_depth=2)

    fusion = FusionOrchestrator()
    fused_context = fusion.fuse_and_rerank(vector_results=vector_results, graph_results=graph_results)
    assert fused_context is not None
    print("  ✓ Module 4 Query Planning, Hybrid Fusion & Reranking Passed.")

    # -------------------------------------------------------------
    # STEP 5: MODULE 5 - Enterprise Gateway, ABAC & Multi-Format Transformer
    # -------------------------------------------------------------
    print("\n[Step 5] Testing Module 5: Enterprise Gateway, ABAC & Formatting...")
    policy_engine = ABACPolicyEngine()
    is_authorized = policy_engine.authorize(
        user_clearance=user_clearance,
        required_clearance="SECRET",
        resource_tenant=tenant_id,
        user_tenant=tenant_id
    )
    assert is_authorized is True

    query_normalizer = DirtyQueryNormalizer()
    clean_query = query_normalizer.normalize_query("Who leads Projct Phœnix development?")
    assert "Phoenix" in clean_query or "Project" in clean_query

    transformer = MultiFormatTransformer()
    markdown_output = transformer.to_markdown(context=fused_context, query=clean_query)
    json_output = transformer.to_json(context=fused_context, query=clean_query)
    
    assert markdown_output is not None and len(markdown_output) > 0
    assert json_output is not None and "query" in json_output
    print("  ✓ Module 5 Gateway ABAC Clearance, Query Normalization & Formatting Passed.")

    print("\n" + "=" * 70)
    print("SUCCESS: ALL 5 MODULES ARE PROPERLY WIRED & INTEGRATED END-TO-END!")
    print("=" * 70)

if __name__ == "__main__":
    verify_m1_to_m5_connection()
