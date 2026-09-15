-- Company Brain Enterprise Database Schema & Security Definition (Production Scale)
-- Architecture: Event-Driven Document Intelligence -> Embedding Model Registry -> Knowledge Lineage -> Retrieval Interface
-- PostgreSQL + pgvector + Apache AGE Graph Extension

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Drop old tables for clean migration
DROP TABLE IF EXISTS pipeline_metrics CASCADE;
DROP TABLE IF EXISTS connector_sync_cursors CASCADE;
DROP TABLE IF EXISTS embedding_models CASCADE;
DROP TABLE IF EXISTS document_versions CASCADE;
DROP TABLE IF EXISTS entity_relationships CASCADE;
DROP TABLE IF EXISTS entity_mentions CASCADE;
DROP TABLE IF EXISTS entity_aliases CASCADE;
DROP TABLE IF EXISTS entities CASCADE;
DROP TABLE IF EXISTS embeddings CASCADE;
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS document_ocr CASCADE;
DROP TABLE IF EXISTS document_images CASCADE;
DROP TABLE IF EXISTS document_tables CASCADE;
DROP TABLE IF EXISTS document_sections CASCADE;
DROP TABLE IF EXISTS document_pages CASCADE;
DROP TABLE IF EXISTS document_metadata CASCADE;
DROP TABLE IF EXISTS document_processing_jobs CASCADE;

-- 1. Tenants Table
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    -- Per-tenant overrides (embedding model, chunk policy, feature flags) — see
    -- app/core_config/tenant_config_service.py. Real persistence: previously this
    -- service could never actually be configured (no setter existed at all), so it
    -- always silently fell through to hardcoded defaults.
    settings JSONB DEFAULT '{}'::jsonb
);

-- 2. Users Table (Enterprise Accounts & RBAC)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(64) DEFAULT 'admin',
    department VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

-- 3. Documents Table (Root Parent Entity with Governance Lifecycle)
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_app VARCHAR(64) NOT NULL,         -- e.g. 'slack', 'google_drive', 'github', 'jira'
    resource_category VARCHAR(64) NOT NULL,  -- e.g. 'chat_message', 'doc', 'code_pr', 'ticket', 'video'
    resource_type VARCHAR(64) NOT NULL,      -- e.g. 'message', 'file', 'pull_request', 'issue'
    external_id VARCHAR(512) NOT NULL,       -- Native ID from source app
    
    title TEXT,
    content TEXT,                             -- Full clean text representation
    has_transcript BOOLEAN DEFAULT FALSE,
    has_ocr_text BOOLEAN DEFAULT FALSE,

    -- Data Lifecycle & Governance State
    lifecycle_state VARCHAR(64) NOT NULL DEFAULT 'active', -- 'active', 'archived', 'retention_expired', 'deleted'
    current_version_number INT DEFAULT 1,

    -- Object Storage Reference
    s3_bucket VARCHAR(255) NOT NULL,
    s3_key TEXT NOT NULL,
    is_compressed BOOLEAN DEFAULT TRUE,
    file_size_bytes BIGINT DEFAULT 0,
    mime_type VARCHAR(128) DEFAULT 'application/json',
    etag VARCHAR(255),

    -- Additional Metadata (JSONB)
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Points this document at a channel-level ACL group (see resource_group_acls
    -- below) instead of per-document ACLs. NULL for GitHub and anything else using
    -- document_acls directly — existing per-document ACL behavior is unaffected.
    resource_group_id VARCHAR(255) DEFAULT NULL,

    -- Audit Timestamps
    -- Real bug found via live Admin Dashboard testing 2026-08-23: created_at
    -- had no DEFAULT, and none of the five real writers into this table
    -- (manual upload, connector ingestion, 3 webhook paths — grepped every
    -- real "INSERT INTO documents" in the app) ever set it explicitly, so
    -- every real document ever ingested through any live path had a NULL
    -- created_at. This silently broke "ORDER BY created_at DESC" everywhere
    -- it's used (Documents panel, Library) and showed as "Invalid Date" in
    -- the Admin Dashboard's recent-documents list.
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ DEFAULT now(),
    archived_at TIMESTAMPTZ DEFAULT NULL,
    deleted_at TIMESTAMPTZ DEFAULT NULL,

    -- Real Postgres full-text search over document titles (keyword/title-match signal
    -- for hybrid retrieval — replaces substring LIKE matching).
    title_search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(title, ''))) STORED,

    CONSTRAINT unique_tenant_source_external UNIQUE (tenant_id, source_app, external_id)
);
CREATE INDEX idx_documents_fts ON documents USING GIN (title_search_vector);
CREATE INDEX IF NOT EXISTS idx_documents_resource_group ON documents(tenant_id, source_app, resource_group_id) WHERE resource_group_id IS NOT NULL;

-- Upgrade existing documents table if columns missing
ALTER TABLE documents ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(64) NOT NULL DEFAULT 'active';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS current_version_number INT DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_documents_tenant_app ON documents(tenant_id, source_app);
CREATE INDEX IF NOT EXISTS idx_documents_lifecycle ON documents(tenant_id, lifecycle_state);

-- =====================================================================
-- 4. DOCUMENT VERSIONS (Explicit Version History & Audit Trail)
-- =====================================================================
CREATE TABLE document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    checksum VARCHAR(128) NOT NULL,
    s3_key TEXT NOT NULL,
    file_size_bytes BIGINT DEFAULT 0,
    change_summary TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_doc_version UNIQUE (tenant_id, document_id, version_number)
);

CREATE INDEX idx_doc_versions_lookup ON document_versions(tenant_id, document_id, version_number);

-- =====================================================================
-- 5. CONNECTOR SYNC CURSORS & VERSIONING (Resumable Incremental Syncs)
-- =====================================================================
CREATE TABLE connector_sync_cursors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_app VARCHAR(64) NOT NULL,
    connector_version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    api_version VARCHAR(32) NOT NULL DEFAULT 'v1',
    sync_cursor TEXT,
    last_synced_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_app_cursor UNIQUE (tenant_id, source_app)
);

CREATE INDEX idx_sync_cursors_lookup ON connector_sync_cursors(tenant_id, source_app);

-- =====================================================================
-- 6. EMBEDDING MODEL REGISTRY (Multi-Model Vector Management)
-- =====================================================================
CREATE TABLE embedding_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name VARCHAR(128) UNIQUE NOT NULL,
    provider VARCHAR(64) NOT NULL DEFAULT 'self-hosted',
    dimension INT NOT NULL DEFAULT 1024,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO embedding_models (model_name, provider, dimension, status)
VALUES ('BAAI/bge-large-en-v1.5', 'self-hosted', 1024, 'active')
ON CONFLICT (model_name) DO NOTHING;

-- =====================================================================
-- 7. PIPELINE JOBS & METRICS (State Machine & Observability Telemetry)
-- =====================================================================
CREATE TABLE document_processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number INT DEFAULT 1,
    pipeline_stage VARCHAR(64) NOT NULL DEFAULT 'queued',
    status VARCHAR(64) NOT NULL DEFAULT 'queued',
    priority INT DEFAULT 50,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    worker_id VARCHAR(255),
    parent_job_id UUID REFERENCES document_processing_jobs(id) ON DELETE CASCADE,
    error_message TEXT,
    execution_time_ms BIGINT DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_doc_job UNIQUE (tenant_id, document_id)
);

CREATE INDEX idx_proc_jobs_lookup ON document_processing_jobs(tenant_id, status, priority);

CREATE TABLE pipeline_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    stage VARCHAR(64) NOT NULL,
    duration_ms BIGINT NOT NULL,
    items_processed INT DEFAULT 1,
    success BOOLEAN DEFAULT TRUE,
    error_type VARCHAR(128),
    timestamp TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_pipeline_metrics_lookup ON pipeline_metrics(tenant_id, stage, timestamp);

-- =====================================================================
-- 8. DOCUMENT INTELLIGENCE LAYER (Document -> Pages -> Sections -> Tables/Images/OCR)
-- =====================================================================

CREATE TABLE document_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NOT NULL,
    width INT,
    height INT,
    page_text TEXT,
    layout_bbox JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_doc_page UNIQUE (tenant_id, document_id, page_number)
);

CREATE INDEX idx_doc_pages_lookup ON document_pages(tenant_id, document_id, page_number);

CREATE TABLE document_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_id UUID REFERENCES document_pages(id) ON DELETE SET NULL,
    parent_section_id UUID REFERENCES document_sections(id) ON DELETE CASCADE,
    section_order INT NOT NULL,
    heading TEXT NOT NULL,
    level INT DEFAULT 1,
    content TEXT NOT NULL,
    token_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_doc_sections_lookup ON document_sections(tenant_id, document_id, section_order);

CREATE TABLE document_tables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_id UUID REFERENCES document_pages(id) ON DELETE SET NULL,
    page_number INT DEFAULT 1,
    table_number INT NOT NULL,
    rows_count INT DEFAULT 0,
    cols_count INT DEFAULT 0,
    grid_markdown TEXT NOT NULL,
    data_json JSONB DEFAULT '[]'::jsonb,
    data_csv TEXT,
    confidence FLOAT DEFAULT 1.0,
    bbox JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_doc_tables_lookup ON document_tables(tenant_id, document_id, table_number);

CREATE TABLE document_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_id UUID REFERENCES document_pages(id) ON DELETE SET NULL,
    page_number INT DEFAULT 1,
    image_index INT NOT NULL,
    mime_type VARCHAR(128) DEFAULT 'image/png',
    image_hash VARCHAR(128),
    s3_key TEXT,
    thumbnail_path TEXT,
    width INT,
    height INT,
    detected_objects JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_doc_images_lookup ON document_images(tenant_id, document_id, image_index);

CREATE TABLE document_ocr (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    image_id UUID REFERENCES document_images(id) ON DELETE CASCADE,
    page_id UUID REFERENCES document_pages(id) ON DELETE CASCADE,
    ocr_engine VARCHAR(64) DEFAULT 'Tesseract 5',
    confidence FLOAT DEFAULT 1.0,
    ocr_text TEXT NOT NULL,
    extracted_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_doc_ocr_lookup ON document_ocr(tenant_id, document_id);

CREATE TABLE document_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    checksum VARCHAR(128) NOT NULL,
    source_connector VARCHAR(128) NOT NULL,
    language VARCHAR(32) DEFAULT 'en',
    mime_type VARCHAR(128),
    file_size_bytes BIGINT DEFAULT 0,
    version VARCHAR(32) DEFAULT '1.0',
    encryption_status VARCHAR(64) DEFAULT 'AES-256',
    retention_policy VARCHAR(64) DEFAULT 'standard',
    custom_metadata JSONB DEFAULT '{}'::jsonb,
    extracted_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_doc_meta UNIQUE (tenant_id, document_id)
);

CREATE INDEX idx_doc_metadata_lookup ON document_metadata(tenant_id, document_id);

-- =====================================================================
-- 9. EMBEDDING LAYER (Decoupled Chunks & Vector Store)
-- =====================================================================

CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id UUID REFERENCES document_sections(id) ON DELETE CASCADE,
    page_id UUID REFERENCES document_pages(id) ON DELETE SET NULL,
    chunk_index INT NOT NULL,
    heading TEXT,
    text_content TEXT NOT NULL,
    token_count INT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    -- Real Postgres full-text search (replaces substring LIKE keyword matching).
    text_search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text_content)) STORED
);

CREATE INDEX idx_doc_chunks_lookup ON document_chunks(tenant_id, document_id, chunk_index);
CREATE INDEX idx_doc_chunks_section ON document_chunks(tenant_id, section_id);
CREATE INDEX idx_doc_chunks_fts ON document_chunks USING GIN (text_search_vector);

CREATE TABLE embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    model_name VARCHAR(128) NOT NULL DEFAULT 'BAAI/bge-large-en-v1.5',
    dimension INT NOT NULL DEFAULT 1024,
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_chunk_model UNIQUE (tenant_id, chunk_id, model_name)
);

CREATE INDEX idx_embeddings_tenant_chunk ON embeddings(tenant_id, chunk_id);
CREATE INDEX idx_embeddings_vector_hnsw ON embeddings 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- =====================================================================
-- 10. KNOWLEDGE LAYER & SOURCE PROVENANCE (Canonical Entities, Aliases & Graph Lineage)
-- =====================================================================

CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    canonical_name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    description TEXT,
    attributes JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_canonical_entity UNIQUE (tenant_id, canonical_name, entity_type)
);

CREATE INDEX idx_entities_lookup ON entities(tenant_id, entity_type, canonical_name);

CREATE TABLE entity_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias_name VARCHAR(255) NOT NULL,
    source_app VARCHAR(64) NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_alias UNIQUE (tenant_id, alias_name, source_app)
);

CREATE INDEX idx_aliases_lookup ON entity_aliases(tenant_id, alias_name);

CREATE TABLE entity_mentions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_id UUID REFERENCES document_pages(id) ON DELETE SET NULL,
    section_id UUID REFERENCES document_sections(id) ON DELETE SET NULL,
    chunk_id UUID REFERENCES document_chunks(id) ON DELETE SET NULL,
    mention_text VARCHAR(255) NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    extraction_run_id UUID,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_mentions_lookup ON entity_mentions(tenant_id, entity_id, document_id);
CREATE INDEX idx_mentions_provenance ON entity_mentions(tenant_id, document_id, section_id, chunk_id);

CREATE TABLE entity_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relationship_type VARCHAR(64) NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    page_id UUID REFERENCES document_pages(id) ON DELETE SET NULL,
    section_id UUID REFERENCES document_sections(id) ON DELETE SET NULL,
    chunk_id UUID REFERENCES document_chunks(id) ON DELETE SET NULL,
    extraction_run_id UUID,
    attributes JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_rel_lookup ON entity_relationships(tenant_id, source_entity_id, target_entity_id);
CREATE INDEX idx_rel_provenance ON entity_relationships(tenant_id, document_id, chunk_id);

-- =====================================================================
-- SECURITY & AUXILIARY TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS document_acls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    principal_type VARCHAR(64) NOT NULL,
    principal_external_id VARCHAR(255) NOT NULL,
    permission VARCHAR(64) NOT NULL DEFAULT 'read',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_acls_doc ON document_acls(document_id);
CREATE INDEX IF NOT EXISTS idx_acls_lookup ON document_acls(tenant_id, principal_type, principal_external_id);

-- Document Pins (Library, Module 6C 2026-08-23): backs the "Library" panel —
-- a real, per-user curated subset of Documents, not a fabricated separate
-- concept. Documents lists everything a caller can see; Library is what
-- they've deliberately chosen to keep close. Re-verified against the real
-- ACL query at read time (workspace_router.py's /library endpoint), so
-- revoking a document's ACL later also drops it out of a user's Library,
-- not just out of Documents. user_id is VARCHAR, matching the existing
-- convention in conversation_sessions (the caller's real user_id captured
-- at login, not necessarily strictly re-validated against users.id).
CREATE TABLE IF NOT EXISTS document_pins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    pinned_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (tenant_id, user_id, document_id)
);
CREATE INDEX IF NOT EXISTS idx_document_pins_lookup ON document_pins(tenant_id, user_id);

-- Channel-level ACLs (2026-08-20, Slack connector prep): document_acls above is
-- per-document, one row per principal — correct for GitHub (permissions genuinely
-- vary per PR/issue) but wrong for Slack, where permission is really a property of
-- the channel, not each individual message. Fanning that out per-message would mean
-- one row per (message, channel member) — for a 500-person channel, 500 rows per
-- message. This table stores channel membership once; documents.resource_group_id
-- (NULL for GitHub/anything using per-document ACLs) points a document at its group.
CREATE TABLE IF NOT EXISTS resource_group_acls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_app VARCHAR(64) NOT NULL,          -- e.g. 'slack'
    resource_group_id VARCHAR(255) NOT NULL,  -- e.g. Slack channel ID
    principal_type VARCHAR(64) NOT NULL,
    principal_external_id VARCHAR(255) NOT NULL,
    permission VARCHAR(64) NOT NULL DEFAULT 'read',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (tenant_id, source_app, resource_group_id, principal_type, principal_external_id)
);
CREATE INDEX IF NOT EXISTS idx_resource_group_acls_lookup ON resource_group_acls(tenant_id, source_app, resource_group_id);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_app VARCHAR(64) NOT NULL,
    encrypted_access_token TEXT NOT NULL,
    encrypted_refresh_token TEXT,
    token_type VARCHAR(64) DEFAULT 'Bearer',
    scopes TEXT[],
    expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT now(),
    config JSONB DEFAULT '{}'::jsonb,  -- connector-specific settings, e.g. {"owner": "...", "repo": "..."} for GitHub

    CONSTRAINT unique_tenant_app_token UNIQUE (tenant_id, source_app)
);

CREATE TABLE IF NOT EXISTS sync_statuses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_app VARCHAR(64) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'idle',
    total_items_synced BIGINT DEFAULT 0,
    failed_items_count BIGINT DEFAULT 0,
    last_synced_at TIMESTAMPTZ,
    error_message TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_app_sync UNIQUE (tenant_id, source_app)
);

CREATE TABLE IF NOT EXISTS ingestion_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_app VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    items_processed INT DEFAULT 0,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================================
-- ROW-LEVEL SECURITY (RLS) ENFORCEMENT ON ALL TABLES
-- =====================================================================

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE connector_sync_cursors ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_processing_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_tables ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_ocr ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_mentions ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_acls ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_statuses ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_audit_logs ENABLE ROW LEVEL SECURITY;

ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE document_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE connector_sync_cursors FORCE ROW LEVEL SECURITY;
ALTER TABLE document_processing_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE pipeline_metrics FORCE ROW LEVEL SECURITY;
ALTER TABLE document_pages FORCE ROW LEVEL SECURITY;
ALTER TABLE document_sections FORCE ROW LEVEL SECURITY;
ALTER TABLE document_tables FORCE ROW LEVEL SECURITY;
ALTER TABLE document_images FORCE ROW LEVEL SECURITY;
ALTER TABLE document_ocr FORCE ROW LEVEL SECURITY;
ALTER TABLE document_metadata FORCE ROW LEVEL SECURITY;
ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE embeddings FORCE ROW LEVEL SECURITY;
ALTER TABLE entities FORCE ROW LEVEL SECURITY;
ALTER TABLE entity_aliases FORCE ROW LEVEL SECURITY;
ALTER TABLE entity_mentions FORCE ROW LEVEL SECURITY;
ALTER TABLE entity_relationships FORCE ROW LEVEL SECURITY;
ALTER TABLE document_acls FORCE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens FORCE ROW LEVEL SECURITY;
ALTER TABLE sync_statuses FORCE ROW LEVEL SECURITY;
ALTER TABLE ingestion_audit_logs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS users_tenant_isolation ON users;
CREATE POLICY users_tenant_isolation ON users USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS documents_tenant_isolation ON documents;
CREATE POLICY documents_tenant_isolation ON documents USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS versions_tenant_isolation ON document_versions;
CREATE POLICY versions_tenant_isolation ON document_versions USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS cursors_tenant_isolation ON connector_sync_cursors;
CREATE POLICY cursors_tenant_isolation ON connector_sync_cursors USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS proc_jobs_tenant_isolation ON document_processing_jobs;
CREATE POLICY proc_jobs_tenant_isolation ON document_processing_jobs USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS metrics_tenant_isolation ON pipeline_metrics;
CREATE POLICY metrics_tenant_isolation ON pipeline_metrics USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS pages_tenant_isolation ON document_pages;
CREATE POLICY pages_tenant_isolation ON document_pages USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS sections_tenant_isolation ON document_sections;
CREATE POLICY sections_tenant_isolation ON document_sections USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS tables_tenant_isolation ON document_tables;
CREATE POLICY tables_tenant_isolation ON document_tables USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS images_tenant_isolation ON document_images;
CREATE POLICY images_tenant_isolation ON document_images USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS ocr_tenant_isolation ON document_ocr;
CREATE POLICY ocr_tenant_isolation ON document_ocr USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS metadata_tenant_isolation ON document_metadata;
CREATE POLICY metadata_tenant_isolation ON document_metadata USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS chunks_tenant_isolation ON document_chunks;
CREATE POLICY chunks_tenant_isolation ON document_chunks USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS embeddings_tenant_isolation ON embeddings;
CREATE POLICY embeddings_tenant_isolation ON embeddings USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS entities_tenant_isolation ON entities;
CREATE POLICY entities_tenant_isolation ON entities USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS aliases_tenant_isolation ON entity_aliases;
CREATE POLICY aliases_tenant_isolation ON entity_aliases USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS mentions_tenant_isolation ON entity_mentions;
CREATE POLICY mentions_tenant_isolation ON entity_mentions USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS rel_tenant_isolation ON entity_relationships;
CREATE POLICY rel_tenant_isolation ON entity_relationships USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS document_acls_tenant_isolation ON document_acls;
CREATE POLICY document_acls_tenant_isolation ON document_acls USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS oauth_tokens_tenant_isolation ON oauth_tokens;
CREATE POLICY oauth_tokens_tenant_isolation ON oauth_tokens USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS sync_statuses_tenant_isolation ON sync_statuses;
CREATE POLICY sync_statuses_tenant_isolation ON sync_statuses USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS audit_logs_tenant_isolation ON ingestion_audit_logs;
CREATE POLICY audit_logs_tenant_isolation ON ingestion_audit_logs USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

-- =====================================================================
-- TENANT INVITES (real invite system, 2026-08-21)
-- =====================================================================
-- Before this, signup either created a brand-new tenant, or — the bug fixed the same
-- day — silently let anyone claiming to know an existing tenant's domain join it as
-- admin. Rejecting that outright closed the hole but left no way for a real admin to
-- actually bring a teammate in. This table is that real path: an admin creates an
-- invite scoped to one specific email + role; only the SHA-256 hash is stored (same
-- principle as mcp_api_keys — the raw token is shown once, never read back, only
-- ever compared); single-use, enforced by used_at; time-bound, enforced by expires_at.
CREATE TABLE IF NOT EXISTS tenant_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invited_by_user_id UUID NOT NULL,
    email VARCHAR(255) NOT NULL,  -- bound to a specific invitee, not redeemable by anyone who sees the link
    role VARCHAR(64) NOT NULL DEFAULT 'member',
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_tenant_invites_hash ON tenant_invites(token_hash) WHERE used_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_tenant_invites_tenant ON tenant_invites(tenant_id);

-- Same pre-auth-lookup shape as mcp_api_keys: redeeming an invite means looking it up
-- by hash BEFORE any tenant context exists, so the policy has to permit that specific
-- case (no tenant context set) while still isolating normal tenant-scoped queries.
ALTER TABLE tenant_invites ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_invites_tenant_isolation ON tenant_invites;
CREATE POLICY tenant_invites_tenant_isolation ON tenant_invites USING (
    current_setting('app.current_tenant_id', true) IS NULL
    OR current_setting('app.current_tenant_id', true) = ''
    OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);

-- =====================================================================
-- MCP API KEYS (Module 10 — external AI connectivity, 2026-08-20)
-- =====================================================================
-- Real per-tenant bearer keys for the MCP server (app/api/mcp_server_router.py).
-- Only the SHA-256 hash is ever stored — the raw key is shown once at creation time
-- and cannot be recovered, same principle as GitHub/Stripe-style API keys (never
-- AES-encrypted-and-decryptable like oauth_tokens, since nothing needs to read it back).
CREATE TABLE IF NOT EXISTS mcp_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL DEFAULT 'Default MCP Key',
    created_at TIMESTAMPTZ DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_hash ON mcp_api_keys(key_hash) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_tenant ON mcp_api_keys(tenant_id);

-- Real constraint this policy has to account for: resolving "which tenant does this
-- raw key belong to" is inherently a PRE-tenant-context lookup — the app can't
-- SET_CONFIG app.current_tenant_id before it knows the answer. A standard
-- tenant-match-only policy would deadlock that query. Security here is instead
-- provided by key_hash's uniqueness and 256 bits of real randomness (see the /keys
-- generation endpoint) — an empty session context may look up by hash (finding at
-- most one row, by construction), but once a tenant context IS set, cross-tenant rows
-- stay invisible exactly as with every other table.
ALTER TABLE mcp_api_keys ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS mcp_api_keys_tenant_isolation ON mcp_api_keys;
CREATE POLICY mcp_api_keys_tenant_isolation ON mcp_api_keys USING (
    current_setting('app.current_tenant_id', true) IS NULL
    OR current_setting('app.current_tenant_id', true) = ''
    OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);

-- =====================================================================
-- APPLICATION CONNECTION ROLE DEFINITION (NON-SUPERUSER WITH NOBYPASSRLS)
-- =====================================================================
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'company_brain_app') THEN
        CREATE ROLE company_brain_app WITH LOGIN PASSWORD 'app_secure_password_2026' NOBYPASSRLS;
    END IF;
END $$;

-- Real bug fixed 2026-08-21: hardcoded 'company_brain' here, but the actual live
-- database (per .env's POSTGRES_DB) is named 'postgres' — this GRANT silently never
-- matched the real database, which was part of why this whole block, despite being
-- correctly designed, was never actually in effect. GRANT ... ON DATABASE requires a
-- literal identifier (current_database() can't be used directly there), so this goes
-- through dynamic SQL to stay correct regardless of what the real database is named.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO company_brain_app', current_database());
END $$;
GRANT USAGE ON SCHEMA public TO company_brain_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO company_brain_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO company_brain_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO company_brain_app;

-- =====================================================================
-- AGENT EXECUTIONS (Module 7 — AI Agent Platform, real slice started 2026-08-21)
-- =====================================================================
-- Real, scoped first step of Module 7: a single read-only Research Agent, not the
-- full multi-agent/tool-approval platform from the Module 7-10 master architecture
-- doc — that stays a documented future build. Every real agent run (plan + each
-- tool call + final result) is persisted here for real observability, matching the
-- "agent execution timeline" concept from that spec. tenant_id is a mandatory,
-- explicitly-filtered column in every query against this table (not just an RLS
-- policy) — the same defense-in-depth pattern used everywhere else this session,
-- since real RLS enforcement is still blocked pending the company_brain_app role fix.
CREATE TABLE IF NOT EXISTS agent_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    agent_type VARCHAR(64) NOT NULL DEFAULT 'research',
    user_request TEXT NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'CREATED',
    plan JSONB,
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    final_result TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_agent_executions_tenant ON agent_executions(tenant_id);
ALTER TABLE agent_executions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS agent_executions_tenant_isolation ON agent_executions;
CREATE POLICY agent_executions_tenant_isolation ON agent_executions USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);

-- =====================================================================
-- CHAT FEEDBACK (real bug found via live testing 2026-08-22)
-- =====================================================================
-- POST /api/v6a/chat/feedback claimed "Feedback recorded" but only ever wrote a
-- transient logger.info() line — no table existed, so every real thumbs up/down a
-- user ever submitted vanished the moment that log line rotated or the process
-- restarted, despite the API telling the user it was durably saved. turn_id is a
-- plain string (the real generated turn id, e.g. "turn_ab12cd34") rather than a
-- foreign key — there's no separate persisted "turns" table to reference against;
-- it's still real and traceable back to server logs for a given tenant/session.
CREATE TABLE IF NOT EXISTS chat_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    turn_id VARCHAR(255) NOT NULL,
    feedback VARCHAR(16) NOT NULL,  -- 'up' or 'down'
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_tenant ON chat_feedback(tenant_id);
CREATE INDEX IF NOT EXISTS idx_chat_feedback_turn ON chat_feedback(turn_id);
ALTER TABLE chat_feedback ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chat_feedback_tenant_isolation ON chat_feedback;
CREATE POLICY chat_feedback_tenant_isolation ON chat_feedback USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);

-- Module 5 (Gateway/EKAP) real, persistent, RLS-protected audit log for
-- /api/v1/search requests. Replaces the prior in-memory-only AuditLogger
-- (app/gateway/audit/audit_logger.py), which claimed "Immutable audit trail
-- writer" while actually holding records in a plain Python list that vanished
-- on every restart. Modeled on the existing ingestion_audit_logs table, but
-- scoped to gateway search/query events rather than ingestion events.
CREATE TABLE IF NOT EXISTS gateway_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    role VARCHAR(64) NOT NULL,
    auth_method VARCHAR(16) NOT NULL,  -- 'jwt' or 'api_key'
    endpoint VARCHAR(128) NOT NULL,
    query TEXT NOT NULL,
    result_count INT DEFAULT 0,
    confidence_score FLOAT DEFAULT 0.0,
    cost_units INT DEFAULT 0,
    latency_ms FLOAT DEFAULT 0.0,
    correlation_id VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gateway_audit_log_tenant ON gateway_audit_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_gateway_audit_log_created ON gateway_audit_log(created_at);
ALTER TABLE gateway_audit_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gateway_audit_log_tenant_isolation ON gateway_audit_log;
CREATE POLICY gateway_audit_log_tenant_isolation ON gateway_audit_log USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);

-- Module 6B (2026-08-22): real durable conversation history + Projects.
-- Before this, ConversationService's session/turn history lived only in
-- InMemorySessionRepository (app/conversation/session/memory_repo.py) — a
-- plain Python dict inside one process. A server restart, crash, or any
-- multi-instance/horizontal-scaling deployment wiped or fragmented every
-- tenant's entire conversation history with no way to recover it. This is
-- the real, durable replacement: PostgresSessionRepository (see
-- app/conversation/session/postgres_repo.py) implements the exact same
-- BaseSessionRepository interface as the in-memory version it replaces.
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_by VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);

-- Scheduled Queries (Module 6C, 2026-08-23): backs the real "Scheduled"
-- panel — a saved question that re-runs itself on an interval and keeps its
-- latest real answer. Deliberately NOT built on Celery Beat: Redis is
-- confirmed unreachable in this environment (see the .env-lost memory from
-- 2026-08-19 — never restored), so a Celery-beat-based scheduler would be
-- real code with no way to actually verify it fires. Runs instead via a
-- plain in-process asyncio loop (app/scheduler/query_scheduler.py) that
-- needs nothing but Postgres — genuinely real and genuinely testable.
CREATE TABLE IF NOT EXISTS scheduled_queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    query_text TEXT NOT NULL,
    persona VARCHAR(64) NOT NULL DEFAULT 'CTO',
    interval_seconds INT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_run_at TIMESTAMPTZ,
    last_status VARCHAR(32),      -- 'ok' | 'error' | NULL (never run yet)
    last_answer TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_scheduled_queries_tenant ON scheduled_queries(tenant_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_queries_due ON scheduled_queries(is_active, next_run_at);

CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    title VARCHAR(500) NOT NULL DEFAULT 'New Conversation',
    state VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    pinned BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_sessions_tenant_user ON conversation_sessions(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_conv_sessions_project ON conversation_sessions(project_id);

CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL REFERENCES conversation_sessions(session_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_query TEXT NOT NULL,
    persona_used VARCHAR(64),
    mode_used VARCHAR(64),
    assistant_response_json JSONB,
    model_name VARCHAR(128),
    latency_ms DOUBLE PRECISION,
    cost_usd DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_turns_session ON conversation_turns(session_id, created_at);

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
ALTER TABLE conversation_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE conversation_turns FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS projects_tenant_isolation ON projects;
CREATE POLICY projects_tenant_isolation ON projects USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);
DROP POLICY IF EXISTS conv_sessions_tenant_isolation ON conversation_sessions;
CREATE POLICY conv_sessions_tenant_isolation ON conversation_sessions USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);
DROP POLICY IF EXISTS conv_turns_tenant_isolation ON conversation_turns;
CREATE POLICY conv_turns_tenant_isolation ON conversation_turns USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
);

