# Company Brain — Master Platform System Architecture (Source of Truth)

## Executive Platform Summary
**Company Brain** is an enterprise-grade Knowledge & Intelligence Engine designed to ingest, embed, organize, index, retrieve, govern, and serve multi-modal organizational knowledge under strict multi-tenant Row-Level Security (RLS).

---

## 🏛️ Master System Architecture Diagram

```mermaid
flowchart TD
    subgraph Layer 1: Ingestion & Privacy (Module 1)
        PDF & DocX & XLSX & Slack & Jira --> Presidio_PII["Presidio PII Redactor"]
        Presidio_PII --> SHA256["SHA-256 Deduplication"]
    end

    subgraph Layer 2: Chunking & Embeddings (Module 2)
        SHA256 --> Chunker["Dynamic Semantic Boundary Chunker"]
        Chunker --> VectorEngine["BGE-M3 Dense (1024d) + BM25 Sparse"]
        VectorEngine --> QdrantDB[("Qdrant Vector Store")]
    end

    subgraph Layer 3: Enterprise Knowledge Graph (Module 3)
        SHA256 --> GraphExtractor["Entity / Fact / Decision Extractor"]
        GraphExtractor --> PGDB[("AWS RDS PostgreSQL + PGVector\n(Row-Level Security RLS)")]
    end

    subgraph Layer 4: Knowledge-Aware GraphRAG Engine (Module 4 - Frozen)
        PGDB & QdrantDB --> GraphRAG["KnowledgeRetrievalService\n(Intent Registry, Execution Planner, Hybrid Fusion, Reranker, Synthesizer)\nReturns KnowledgeContext v1"]
    end

    subgraph Layer 5: Enterprise Knowledge Access Platform - EKAP (Module 5 - Frozen)
        GraphRAG --> EKAP["EKAP API Gateway & SDK Layer\n(Auth, Policy, Validation, Normalization, Resiliency, Transformers, Stream, Jobs, Audit)"]
    end

    subgraph Layer 6-9: Downstream Intelligence Layer (Modules 6-9)
        EKAP --> M6["Module 6: Conversational Grounded RAG"]
        EKAP --> M7["Module 7: Autonomous AI Agent Suite"]
        EKAP --> M8["Module 8: Workflow Automation Engine"]
        EKAP --> M9["Module 9: Executive Intelligence"]
    end
```

---

## 🔒 Security & Multi-Tenant Trust Boundaries

1. **Row-Level Security (RLS)**: Enforced at the PostgreSQL database kernel level (`SET LOCAL app.current_tenant_id = '{tenant_id}'`). Zero possibility of cross-tenant data leakage.
2. **Unified Policy Engine (RBAC + ABAC)**: Filters sensitive payroll/compensation data for non-admin roles and enforces security clearance levels (`Internal`, `Confidential`, `Restricted`).
3. **Presidio PII Redaction**: Redacts SSNs, credit cards, emails, and phone numbers before ingestion.
4. **Immutable Audit Trail**: Records every query, tenant ID, user ID, cost units, result count, and latency timestamp.

---

## 📊 Modules 1–5 Freeze Certification & Test Coverage

- **Total Test Suite**: **78 passed out of 78 tests (100% pass rate across Modules 1–5)**.
- **Freeze Status**: Modules 1 through 5 are **PERMANENTLY FROZEN**. Bug fixes, security patches, and performance optimizations are permitted, but zero architectural redesigns.
- **Contract Boundary**: All downstream modules consume the stable **`KnowledgeContext` v1** schema served via EKAP.
