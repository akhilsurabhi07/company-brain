-- Company Brain Database Schema & Security Definition
-- PostgreSQL + Apache AGE Graph Extension

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Tenants Table
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Users Table (Enterprise Login & Account Management)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(64) DEFAULT 'admin', -- 'admin', 'employee', 'manager'
    department VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

-- 3. Documents Table (Content & Metadata Storage)
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_app VARCHAR(64) NOT NULL,         -- e.g. 'slack', 'google_drive', 'github', 'jira'
    resource_category VARCHAR(64) NOT NULL,  -- e.g. 'chat_message', 'doc', 'code_pr', 'ticket', 'video'
    resource_type VARCHAR(64) NOT NULL,      -- e.g. 'message', 'file', 'pull_request', 'issue'
    external_id VARCHAR(512) NOT NULL,       -- Native ID from source app
    
    title TEXT,
    content TEXT,                             -- Extracted plain text / transcript / OCR text
    has_transcript BOOLEAN DEFAULT FALSE,
    has_ocr_text BOOLEAN DEFAULT FALSE,

    -- S3 Storage & Compression Reference
    s3_bucket VARCHAR(255) NOT NULL,
    s3_key TEXT NOT NULL,                     -- e.g. raw/{tenant_id}/{source_app}/{resource_type}/{external_id}.json.zst
    is_compressed BOOLEAN DEFAULT TRUE,      -- TRUE if stored with Zstandard (.zst)
    file_size_bytes BIGINT DEFAULT 0,
    mime_type VARCHAR(128) DEFAULT 'application/json',
    etag VARCHAR(255),

    -- Additional App-Specific Metadata (JSONB)
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Audit Timestamps
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ DEFAULT now(),
    deleted_at TIMESTAMPTZ DEFAULT NULL,

    CONSTRAINT unique_tenant_source_external UNIQUE (tenant_id, source_app, external_id)
);

-- Indexes for Document Lookup & Performance
CREATE INDEX IF NOT EXISTS idx_documents_tenant_app ON documents(tenant_id, source_app);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(tenant_id, resource_category);
CREATE INDEX IF NOT EXISTS idx_documents_deleted ON documents(tenant_id, deleted_at) WHERE deleted_at IS NULL;

-- 4. Document ACLs Table (Fine-grained Permissions)
CREATE TABLE IF NOT EXISTS document_acls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    principal_type VARCHAR(64) NOT NULL,      -- 'user', 'group', 'domain', 'public'
    principal_external_id VARCHAR(255) NOT NULL,
    permission VARCHAR(64) NOT NULL DEFAULT 'read', -- 'read', 'write', 'admin'
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_acls_doc ON document_acls(document_id);
CREATE INDEX IF NOT EXISTS idx_acls_lookup ON document_acls(tenant_id, principal_type, principal_external_id);

-- 5. OAuth Tokens Table (Encrypted Token Store)
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

-- 6. Sync Status Telemetry Table
CREATE TABLE IF NOT EXISTS sync_statuses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_app VARCHAR(64) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'idle', -- 'idle', 'backfilling', 'incremental', 'error', 'rate_limited'
    total_items_synced BIGINT DEFAULT 0,
    failed_items_count BIGINT DEFAULT 0,
    last_synced_at TIMESTAMPTZ,
    error_message TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_tenant_app_sync UNIQUE (tenant_id, source_app)
);

-- 7. Ingestion Audit Logs
CREATE TABLE IF NOT EXISTS ingestion_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_app VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,              -- 'backfill_start', 'backfill_complete', 'webhook_received', 'item_deleted'
    items_processed INT DEFAULT 0,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Row Level Security (RLS) Enablement & Force RLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_acls ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_statuses ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_audit_logs ENABLE ROW LEVEL SECURITY;

ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE document_acls FORCE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens FORCE ROW LEVEL SECURITY;
ALTER TABLE sync_statuses FORCE ROW LEVEL SECURITY;
ALTER TABLE ingestion_audit_logs FORCE ROW LEVEL SECURITY;

-- RLS Policies (Session variable: app.current_tenant_id)
DROP POLICY IF EXISTS users_tenant_isolation ON users;
CREATE POLICY users_tenant_isolation ON users
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS documents_tenant_isolation ON documents;
CREATE POLICY documents_tenant_isolation ON documents
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS document_acls_tenant_isolation ON document_acls;
CREATE POLICY document_acls_tenant_isolation ON document_acls
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS oauth_tokens_tenant_isolation ON oauth_tokens;
CREATE POLICY oauth_tokens_tenant_isolation ON oauth_tokens
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS sync_statuses_tenant_isolation ON sync_statuses;
CREATE POLICY sync_statuses_tenant_isolation ON sync_statuses
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS audit_logs_tenant_isolation ON ingestion_audit_logs;
CREATE POLICY audit_logs_tenant_isolation ON ingestion_audit_logs
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
