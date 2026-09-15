import sys
import os
import uuid
import asyncio
import time

sys.path.insert(0, "C:/Users/Surabhi Akhil/OneDrive/Desktop/PCB")
sys.path.insert(0, "C:/Users/Surabhi Akhil/.gemini/antigravity/brain/82259030-8311-4a5c-af32-71cedbfe5073")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text
from app.db.database import async_session_factory
from app.storage.s3_storage import s3_storage
from app.processors.pii_redactor import pii_redactor
from app.processors.semantic_chunker import semantic_chunker
from app.embeddings.bge_embedder import bge_embedder
from app.db.chunk_vector_repo import chunk_vector_repo

# Target Tenants to populate with Mass Enterprise Knowledge Data
TARGET_TENANTS = [
    "00000000-0000-0000-0000-000000000001",
    "11111111-1111-1111-1111-111111111111"
]

MASS_ENTERPRISE_DOCUMENTS = [
    # ─── 1. GITHUB REPOSITORIES & TECHNICAL SPECS ─────────────────────────────
    {
        "source_app": "github",
        "category": "tech_spec",
        "type": "pull_request",
        "ext_id": "gh_pr_108",
        "title": "[GITHUB] PR #108: Quantum Encryption Vault & AES-256-GCM Protocol",
        "content": """# Technical Specification — Quantum Encryption Vault

**Lead Architect**: Alex Rivera
**Repository**: enterprise-org/quantum-vault
**Category**: tech_spec
**Status**: Merged & Deployed

## 1. Cryptographic Protocol Specifications
Quantum Security Vault utilizes **AES-256-GCM** authenticated encryption with HMAC-SHA256 integrity verification. All secret keys are generated using CSPRNG with 256 bits of entropy under strict session RLS boundaries.

## 2. Code Implementation Snippet
```python
def encrypt_payload(data: bytes, key: bytes) -> bytes:
    cipher = AES256GCM(key)
    nonce = os.urandom(12)
    return nonce + cipher.encrypt(nonce, data, None)
```

## 3. Key Rotation & Security SLA
Secret master keys are rotated automatically every 90 days via AWS KMS integration. Data at rest is encrypted prior to AWS S3 bucket persistence."""
    },
    {
        "source_app": "github",
        "category": "cloud_infrastructure",
        "type": "system_spec",
        "ext_id": "gh_spec_401",
        "title": "[GITHUB] Architectural Spec #401: Project Orion System Architecture",
        "content": """# Enterprise System Specification #401 — Project Orion

**Author & Lead Engineer**: Dr. Sarah Lin
**Department**: cloud_infrastructure
**Repository**: enterprise-org/orion-core

## 1. Executive Summary
Project Orion delivers next-generation enterprise capabilities for cloud infrastructure. Under the leadership of Dr. Sarah Lin, the architecture incorporates PostgreSQL 16 Row-Level Security (RLS), pgvector semantic embeddings (1024-dim), and dual-granularity parent-child chunking.

## 2. Technical Milestones & SLA Requirements
Milestone target release date for Project Orion is set for **Q4 2026**. Service level agreements mandate **99.99% uptime** with sub-50ms vector similarity lookup latency.

## 3. Security & Governance Policy
All raw data payloads ingested under Project Orion must pass through PII secret redaction prior to S3 object storage."""
    },
    {
        "source_app": "github",
        "category": "cloud_infrastructure",
        "type": "system_spec",
        "ext_id": "gh_spec_502",
        "title": "[GITHUB] Architectural Spec #502: Project Phoenix Cloud Infrastructure",
        "content": """# Infrastructure Specification #502 — Project Phoenix

**Lead Cloud Architect**: Marcus Vance
**Department**: devops_cloud
**Repository**: enterprise-org/phoenix-infra

## 1. Cloud Architecture Overview
Project Phoenix migrates all legacy workload clusters to AWS ECS Fargate running across multi-AZ availability zones in the AWS Mumbai (ap-south-1) region.

## 2. SLA & Backup Guarantees
Database replication utilizes Amazon RDS Multi-AZ PostgreSQL 16 with automated 35-day point-in-time recovery (PITR). Backup snapshot restoration time (RTO) is guaranteed at under 15 minutes, with zero data loss (RPO < 1 second)."""
    },
    {
        "source_app": "github",
        "category": "security_policy",
        "type": "policy_doc",
        "ext_id": "gh_sec_12",
        "title": "[GITHUB] Security Policy #12: PII Redaction & Secret Redaction Standard",
        "content": """# Enterprise Security Policy #12 — PII & Secret Redaction

**Chief Information Security Officer**: Robert Vance
**Status**: Mandatory Compliance Policy

## 1. Policy Scope
All data connectors (Slack, Jira, GitHub, Google Drive, WhatsApp) must execute regular expression secret scanning before data lands in persistent storage.

## 2. Redacted Patterns
1. AWS Access Keys (`AKIA...`)
2. API Keys (`sk-proj-...`, `sk-or-...`)
3. Database Passwords & Auth Tokens (`POSTGRES_PASSWORD`, `JWT_SECRET`)
4. Social Security Numbers and Credit Card Identifiers"""
    },

    # ─── 2. JIRA SPRINT TICKETS & ARCHITECTURE STORIES ───────────────────────
    {
        "source_app": "jira",
        "category": "sprint_ticket",
        "type": "issue_story",
        "ext_id": "jira_proj_101",
        "title": "[JIRA] PROJ-101: Migration of Legacy Auth to OAuth2 PKCE & JWT Session Tokens",
        "content": """# Jira Issue PROJ-101 — Auth Migration to OAuth2 PKCE

**Reporter**: Elena Rostova (CTO)
**Assignee**: Priya Sharma (Lead Auth Engineer)
**Priority**: Highest
**Sprint**: Sprint 42 (Q1 2026)

## Description
Migrate all enterprise tenant authentication from basic auth header sessions to standard OAuth2 Authorization Code flow with PKCE (Proof Key for Code Exchange).

## Acceptance Criteria
1. Issue RS256 signed JWT tokens containing `tenant_id`, `user_id`, and `role`.
2. Token expiration set to 24 hours with automatic refresh token rotation.
3. Strict verification of `tenant_id` claim in FastAPI dependency layer."""
    },
    {
        "source_app": "jira",
        "category": "sprint_ticket",
        "type": "issue_task",
        "ext_id": "jira_proj_205",
        "title": "[JIRA] PROJ-205: Redis Sliding Window Rate Limiter Implementation",
        "content": """# Jira Issue PROJ-205 — Redis Sliding Window Rate Limiter

**Reporter**: Marcus Vance
**Assignee**: David Sterling
**Priority**: High

## Task Summary
Implement a high-throughput Redis sliding window key rate limiter at the API gateway layer to prevent denial-of-service and enforce tier-based API quotas.

## Technical Details
- Tier Standard: 100 requests per minute.
- Tier Enterprise: 1,000 requests per minute.
- Returns HTTP 429 Too Many Requests when sliding window quota is exhausted."""
    },
    {
        "source_app": "jira",
        "category": "sprint_ticket",
        "type": "issue_epic",
        "ext_id": "jira_proj_309",
        "title": "[JIRA] PROJ-309 Epic: GraphRAG Knowledge Graph Synchronization Engine",
        "content": """# Jira Epic PROJ-309 — GraphRAG Knowledge Graph Sync Engine

**Lead Architect**: Dr. Sarah Lin
**Component**: Graph Intelligence Engine

## Epic Overview
Build an automated GraphRAG extractor that parses entities (Person, Document, Project, Server) and relationships (`AUTHORED_BY`, `DEPENDS_ON`, `BELONGS_TO`) from ingested unstructured documents. Synchronize graph nodes in PostgreSQL with full tenant RLS boundaries."""
    },

    # ─── 3. SLACK & TEAMS COMMUNICATIONS ──────────────────────────────────────
    {
        "source_app": "slack",
        "category": "executive_announcement",
        "type": "channel_message",
        "ext_id": "slack_msg_901",
        "title": "[SLACK] #general: Q3 All-Hands Executive Speech by CEO David Sterling",
        "content": """# Slack Announcement — Q3 All-Hands Meeting Summary

**Sender**: CEO David Sterling
**Channel**: #general
**Date**: October 14, 2025

Team, incredible progress in Q3! Year-over-year ARR growth reached **42%**, driven by strong adoption of our enterprise Knowledge Ingestion Platform.

## Key Executive Highlights:
1. **European Expansion**: Officially launching EU cloud region in Frankfurt by Q2 2026.
2. **Project Orion Milestone**: Dr. Sarah Lin and team are on track for the Q4 2026 release of Project Orion.
3. **Security Commitment**: 100% compliance achieved for ISO 27001 and SOC 2 Type II audits."""
    },
    {
        "source_app": "slack",
        "category": "engineering_qa",
        "type": "channel_message",
        "ext_id": "slack_msg_902",
        "title": "[SLACK] #engineering: CTO Elena Rostova's Tech Stack Guidelines",
        "content": """# Slack Discussion — Engineering Architecture Principles

**Sender**: CTO Elena Rostova
**Channel**: #engineering

Hi team, as we scale our RAG intelligence engine, please ensure all new microservices adhere to our core tech stack:

1. **Framework**: FastAPI (Async Python 3.11)
2. **Database**: PostgreSQL 16 with `pgvector` HNSW vector indexes
3. **Embeddings**: SentenceTransformers `BAAI/bge-large-en-v1.5` (1024 dimensions)
4. **Tenant Isolation**: Mandatory PostgreSQL Row-Level Security (`app.current_tenant_id`)
5. **Storage**: AWS S3 with Zstandard (`.json.zst`) payload compression"""
    },
    {
        "source_app": "teams",
        "category": "devops_report",
        "type": "channel_message",
        "ext_id": "teams_msg_401",
        "title": "[TEAMS] #devops: AWS Infrastructure Cost Optimization Report",
        "content": """# Microsoft Teams Report — AWS Cloud Optimization

**Sender**: Marcus Vance (DevOps Lead)
**Team**: Infrastructure & SRE

## Monthly Cloud Savings Summary
By converting our RDS PostgreSQL database instances to AWS Savings Plans and enabling Zstandard S3 compression, we reduced monthly cloud infrastructure spend by **$14,200/month**.

Vector similarity search response latency remains ultra-fast at **38ms average** across all tenant workloads."""
    },

    # ─── 4. GOOGLE DRIVE & ENTERPRISE DOCUMENTATION ──────────────────────────
    {
        "source_app": "google_drive",
        "category": "strategic_roadmap",
        "type": "drive_document",
        "ext_id": "gdrive_doc_501",
        "title": "[GOOGLE DRIVE] Strategic Product Roadmap 2026-2027.pdf",
        "content": """# Executive Strategy & Product Roadmap 2026–2027

**Prepared By**: Strategic Product Office
**Classification**: Confidential Enterprise

## 1. Major Product Line Targets
- **Project Orion**: Enterprise Cloud Infrastructure AI (Target Release: Q4 2026)
- **Project Helios**: Real-Time Streaming Analytics (Target Release: Q1 2027)
- **Project Artemis**: Autonomous Multi-Agent Decision Engine (Target Release: Q3 2027)

## 2. Target Markets
Focusing on Fortune 500 financial services, healthcare, and enterprise software companies requiring strict air-gapped or RLS multi-tenant data governance."""
    },
    {
        "source_app": "google_drive",
        "category": "sla_policy",
        "type": "drive_document",
        "ext_id": "gdrive_doc_502",
        "title": "[GOOGLE DRIVE] Enterprise SLA & Disaster Recovery Policy.docx",
        "content": """# Enterprise Service Level Agreement (SLA) & DR Policy

**Author**: Operations Compliance Committee

## 1. Availability Commitment
Company Brain guarantees **99.99% operational availability** per calendar month. In the event of an availability breach below 99.9%, service credits of 15% monthly billing apply.

## 2. Disaster Recovery Targets
- **Recovery Time Objective (RTO)**: Under 15 minutes for complete regional failover.
- **Recovery Point Objective (RPO)**: Under 5 seconds for PostgreSQL WAL archiving to S3."""
    },

    # ─── 5. WHATSAPP BUSINESS & CLIENT LOGS ──────────────────────────────────
    {
        "source_app": "whatsapp",
        "category": "client_communication",
        "type": "chat_transcript",
        "ext_id": "wa_chat_101",
        "title": "[WHATSAPP] Client Feedback Log — Acme Corp Account Lead",
        "content": """# WhatsApp Business Log — Acme Corp Account Review

**Client**: Acme Corporation (Domain: acme.com)
**Account Executive**: Rachel Chen

## Summary of Client Discussion
Acme Corp confirmed deployment approval for their enterprise workspace. They specifically requested:
1. Custom domain routing (`acme.companybrain.ai`).
2. Dedicated AWS S3 bucket isolation for compliance.
3. Confirmation that all employee queries adhere to PostgreSQL Row-Level Security."""
    }
]

async def run_mass_ingestion():
    print("\n==========================================================================")
    print(" 🚀 EXECUTING MASS ENTERPRISE CLOUD DATA GENERATION & INGESTION PIPELINE  ")
    print("==========================================================================")
    
    t0 = time.time()
    total_docs_inserted = 0
    total_chunks_inserted = 0
    total_bytes_stored = 0

    for tenant_id in TARGET_TENANTS:
        print(f"\n--- Ingesting Mass Dataset for Tenant ID: '{tenant_id}' ---")
        
        async with async_session_factory() as session:
            # Set RLS session
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id}
            )
            
            # Ensure tenant record exists
            await session.execute(
                text("""
                    INSERT INTO tenants (id, name, domain)
                    VALUES (:tenant_id, 'Acme Enterprise', :domain)
                    ON CONFLICT (id) DO NOTHING
                """),
                {"tenant_id": tenant_id, "domain": f"tenant_{tenant_id[:8]}.com"}
            )
            await session.commit()

            items_to_upload = []
            docs_metadata_batch = []

            for doc in MASS_ENTERPRISE_DOCUMENTS:
                clean_text = pii_redactor.redact_secrets(doc["content"])
                
                # 1. Save to S3
                s3_key, file_bytes_len = s3_storage.save_raw_json(
                    tenant_id=tenant_id,
                    source_app=doc["source_app"],
                    resource_type=doc["type"],
                    external_id=doc["ext_id"],
                    raw_payload={"title": doc["title"], "content": clean_text},
                    compress=True
                )
                
                temp_doc_id = str(uuid.uuid4())

                # 2. Insert Documents Table Parent Record FIRST & get actual Primary Key (via RETURNING id)
                res = await session.execute(
                    text("""
                        INSERT INTO documents (
                            id, tenant_id, source_app, resource_category, resource_type, external_id,
                            title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                        ) VALUES (
                            :id, :tenant_id, :source_app, :category, :type, :ext_id,
                            :title, :content, :s3_bucket, :s3_key, TRUE, :bytes_len
                        ) ON CONFLICT (tenant_id, source_app, external_id) DO UPDATE 
                        SET content = EXCLUDED.content,
                            file_size_bytes = EXCLUDED.file_size_bytes,
                            updated_at = now()
                        RETURNING id
                    """),
                    {
                        "id": temp_doc_id,
                        "tenant_id": tenant_id,
                        "source_app": doc["source_app"],
                        "category": doc["category"],
                        "type": doc["type"],
                        "ext_id": doc["ext_id"],
                        "title": doc["title"],
                        "content": clean_text,
                        "s3_bucket": s3_storage.bucket_name,
                        "s3_key": s3_key,
                        "bytes_len": file_bytes_len,
                    }
                )
                doc_id = str(res.scalar_one())
                await session.commit()

                # 3. Chunking with Semantic Chunker
                chunks = semantic_chunker.chunk_document(
                    tenant_id=tenant_id,
                    document_id=doc_id,
                    full_text=clean_text,
                    resource_category=doc["category"]
                )

                # 4. Generate 1024-dim PyTorch Embeddings
                chunk_texts = [c.text_content for c in chunks]
                chunk_embeddings = bge_embedder.embed_texts(chunk_texts)

                # 5. Upsert Chunks into PostgreSQL pgvector table
                await chunk_vector_repo.save_chunks_and_embeddings(
                    tenant_id=tenant_id,
                    document_id=doc_id,
                    chunks=chunks,
                    embeddings=chunk_embeddings
                )
                
                total_chunks_inserted += len(chunks)
                print(f"  ✅ [{doc['source_app'].upper()}] '{doc['title'][:65]}...' -> {len(chunks)} chunks, {file_bytes_len} B S3")

 

            # 6. Update Sync Status Telemetry Table
            for app_name in ["slack", "jira", "github", "google_drive", "teams", "whatsapp"]:
                await session.execute(
                    text("""
                        INSERT INTO sync_statuses (tenant_id, source_app, status, total_items_synced, last_synced_at)
                        VALUES (:tenant_id, :source_app, 'synced', 5, now())
                        ON CONFLICT (tenant_id, source_app) DO UPDATE 
                        SET status = 'synced',
                            total_items_synced = sync_statuses.total_items_synced + 5,
                            last_synced_at = now(),
                            updated_at = now()
                    """),
                    {"tenant_id": tenant_id, "source_app": app_name}
                )

            await session.commit()

    elapsed = round(time.time() - t0, 2)
    print("\n==========================================================================")
    print(f" 🎉 MASS INGESTION COMPLETE IN {elapsed}s!")
    print(f"    • Total Documents Ingested: {total_docs_inserted}")
    print(f"    • Total Parent-Child Chunks Created: {total_chunks_inserted}")
    print(f"    • Total AWS S3 Compressed Bytes: {total_bytes_stored} B")
    print(f"    • 1024-dim PyTorch Embeddings: Generated & Stored in PostgreSQL pgvector")
    print("==========================================================================")

if __name__ == "__main__":
    asyncio.run(run_mass_ingestion())
