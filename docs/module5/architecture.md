# Module 5 — Enterprise Knowledge Access Platform (EKAP) Architecture

## Overview & Scope
The **Enterprise Knowledge Access Platform (EKAP)** is the secure, governed access layer through which all applications, SDKs, AI systems, and future integrations consume Company Brain capabilities.

---

## ⚡ Canonical 12-Stage Request Pipeline Flow

1. **API Version Manager** (`versioning/`): Enforces deprecation headers and API version routing (`/api/v1`, `/api/v2`).
2. **Authentication Guard** (`authentication/`): Validates OAuth2/JWT/API Key tokens and injects session-scoped RLS tenant context (`app.current_tenant_id`).
3. **Unified Policy Engine** (`authorization/`): Enforces RBAC & ABAC entitlement rules (e.g. blocking salary/payroll queries for non-admin roles).
4. **Request Validation & Normalization** (`validation/` & `normalization/`): Trims whitespace, resolves entity aliases, and canonicalizes entity names.
5. **Feature Flags & Tenant Quotas** (`feature_flags/` & `infrastructure/`): Enforces Token-Bucket rate limiting (HTTP 429) and tenant canary flags.
6. **Gateway Routers** (`routing/`): Exposes clean HTTP endpoints (`/search`, `/stream`, `/health`).
7. **Application Services** (`services/`): Business logic orchestration and resilience bulkheads.
8. **Knowledge Retrieval Client** (`clients/`): Decoupled adapter consuming Module 4 GraphRAG engine output without modifying Module 4.
9. **Module 4 GraphRAG Engine**: Executes multi-retriever search, hybrid fusion, reranking, synthesis, and returns canonical `KnowledgeContext` v1.
10. **Response Transformation Layer** (`transformers/`): Formats `KnowledgeContext` into Chat Markdown, Dashboard JSON, Agent Schemas, or Mobile Compact JSON.
11. **Client Response Delivery**: Transmits response via HTTP JSON, SSE Stream, or Async Webhook.
12. **Event Bus Publisher** (`events/`): Publishes post-response integration events (`SearchCompletedEvent`, `AuditRecordedEvent`, `MetricsUpdatedEvent`).

---

## Service-Level Objectives (SLOs)

| Metric | P95 Target | P99 Target |
| :--- | :---: | :---: |
| **Authentication Overhead** | $< 10\text{ ms}$ | $< 15\text{ ms}$ |
| **Authorization (RBAC/ABAC)** | $< 5\text{ ms}$ | $< 8\text{ ms}$ |
| **Validation & Normalization** | $< 5\text{ ms}$ | $< 8\text{ ms}$ |
| **Gateway Total Overhead** | $< 20\text{ ms}$ | $< 30\text{ ms}$ |
| **Cache Hit Latency** | $< 10\text{ ms}$ | $< 15\text{ ms}$ |
| **SSE First Token Delay** | $< 200\text{ ms}$ | $< 300\text{ ms}$ |
| **Search API End-to-End** | $< 500\text{ ms}$ | $< 750\text{ ms}$ |
