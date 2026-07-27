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
    updated_at TIMESTAMPTZ DEFAULT now()
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

    -- Audit Timestamps
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ DEFAULT now(),
    archived_at TIMESTAMPTZ DEFAULT NULL,
    deleted_at TIMESTAMPTZ DEFAULT NULL,

    CONSTRAINT unique_tenant_source_external UNIQUE (tenant_id, source_app, external_id)
);

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
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_doc_chunks_lookup ON document_chunks(tenant_id, document_id, chunk_index);
CREATE INDEX idx_doc_chunks_section ON document_chunks(tenant_id, section_id);

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
