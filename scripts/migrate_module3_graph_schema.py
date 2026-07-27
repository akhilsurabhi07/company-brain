"""
AWS RDS PostgreSQL Schema Migration — Phase 2 Module 3
======================================================
Adds 16 normalized graph tables, indexes, constraints, and Row-Level Security (RLS)
policies with FORCE ROW LEVEL SECURITY to support tenant isolation even for database superusers.
"""
import asyncio
from sqlalchemy import text
from app.db.database import engine

TABLE_STATEMENTS = [
    'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
    """
    CREATE TABLE IF NOT EXISTS graph_domain_ontologies (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        entity_type VARCHAR(100) NOT NULL,
        schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_entities (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        entity_type VARCHAR(100) NOT NULL,
        canonical_name VARCHAR(255) NOT NULL,
        state VARCHAR(50) NOT NULL DEFAULT 'Candidate',
        confidence_score FLOAT NOT NULL DEFAULT 1.0,
        trust_score FLOAT NOT NULL DEFAULT 1.0,
        attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
        governance_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
        valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        valid_to TIMESTAMPTZ,
        is_current BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_entity_aliases (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        entity_id UUID NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
        alias_name VARCHAR(255) NOT NULL,
        match_type VARCHAR(50) NOT NULL DEFAULT 'exact',
        confidence FLOAT NOT NULL DEFAULT 1.0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_relationships (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        source_entity_id UUID NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
        target_entity_id UUID NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
        relation_type VARCHAR(100) NOT NULL,
        causal_type VARCHAR(50) NOT NULL DEFAULT 'structural',
        state VARCHAR(50) NOT NULL DEFAULT 'Candidate',
        confidence_score FLOAT NOT NULL DEFAULT 1.0,
        attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
        valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        valid_to TIMESTAMPTZ,
        is_current BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_relationship_sources (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        relationship_id UUID NOT NULL REFERENCES graph_relationships(id) ON DELETE CASCADE,
        document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
        chunk_id UUID REFERENCES document_chunks(id) ON DELETE CASCADE,
        section_id VARCHAR(100),
        page_number INT,
        source_snippet TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_facts (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        fact_type VARCHAR(100) NOT NULL,
        is_derived BOOLEAN NOT NULL DEFAULT FALSE,
        metric_name VARCHAR(255) NOT NULL,
        value VARCHAR(255) NOT NULL,
        period VARCHAR(100),
        state VARCHAR(50) NOT NULL DEFAULT 'Candidate',
        confidence_score FLOAT NOT NULL DEFAULT 1.0,
        source_authority FLOAT NOT NULL DEFAULT 1.0,
        temporal_timestamp TIMESTAMPTZ,
        is_current BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_fact_sources (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        fact_id UUID NOT NULL REFERENCES graph_facts(id) ON DELETE CASCADE,
        document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
        chunk_id UUID REFERENCES document_chunks(id) ON DELETE CASCADE,
        source_snippet TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_conflicts (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        conflict_type VARCHAR(100) NOT NULL,
        entity_id UUID REFERENCES graph_entities(id) ON DELETE SET NULL,
        description TEXT NOT NULL,
        evidence_a_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence_b_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        severity VARCHAR(50) NOT NULL DEFAULT 'medium',
        resolution_status VARCHAR(50) NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_decisions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        decision_title VARCHAR(255) NOT NULL,
        owner_id UUID REFERENCES graph_entities(id) ON DELETE SET NULL,
        rationale TEXT NOT NULL,
        expected_outcome TEXT,
        actual_outcome TEXT,
        state VARCHAR(50) NOT NULL DEFAULT 'Published',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_action_recommendations (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        action_type VARCHAR(100) NOT NULL,
        target_entity_id UUID REFERENCES graph_entities(id) ON DELETE CASCADE,
        recommendation_text TEXT NOT NULL,
        priority VARCHAR(50) NOT NULL DEFAULT 'medium',
        status VARCHAR(50) NOT NULL DEFAULT 'open',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_nodes (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        entity_id UUID NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
        label VARCHAR(255) NOT NULL,
        state VARCHAR(50) NOT NULL DEFAULT 'Published',
        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_edges (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        source_node_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
        target_node_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
        edge_type VARCHAR(100) NOT NULL,
        weight FLOAT NOT NULL DEFAULT 1.0,
        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_workflows (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        workflow_name VARCHAR(255) NOT NULL,
        step_sequence_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        occurrence_count INT NOT NULL DEFAULT 1,
        state VARCHAR(50) NOT NULL DEFAULT 'Active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_knowledge_gaps (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        gap_type VARCHAR(100) NOT NULL,
        entity_id UUID REFERENCES graph_entities(id) ON DELETE SET NULL,
        description TEXT NOT NULL,
        severity VARCHAR(50) NOT NULL DEFAULT 'medium',
        status VARCHAR(50) NOT NULL DEFAULT 'open',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_learning_signals (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        signal_type VARCHAR(100) NOT NULL,
        target_type VARCHAR(100) NOT NULL,
        target_id UUID NOT NULL,
        original_value JSONB NOT NULL DEFAULT '{}'::jsonb,
        user_correction JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_versions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        version_number INT NOT NULL,
        snapshot_hash VARCHAR(128) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_graph_entities_tenant_type ON graph_entities(tenant_id, entity_type)",
    "CREATE INDEX IF NOT EXISTS idx_graph_entities_canonical ON graph_entities(tenant_id, canonical_name)",
    "CREATE INDEX IF NOT EXISTS idx_graph_aliases_name ON graph_entity_aliases(tenant_id, alias_name)",
    "CREATE INDEX IF NOT EXISTS idx_graph_rel_source_target ON graph_relationships(tenant_id, source_entity_id, target_entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_graph_facts_metric ON graph_facts(tenant_id, metric_name)",
    "CREATE INDEX IF NOT EXISTS idx_graph_conflicts_status ON graph_conflicts(tenant_id, resolution_status)",

    # RLS Enablements & Force RLS Policies
    "ALTER TABLE graph_domain_ontologies ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_entities ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_entity_aliases ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_relationships ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_relationship_sources ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_facts ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_fact_sources ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_conflicts ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_decisions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_action_recommendations ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_nodes ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_edges ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_workflows ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_knowledge_gaps ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_learning_signals ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE graph_versions ENABLE ROW LEVEL SECURITY",

    "ALTER TABLE graph_domain_ontologies FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_entities FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_entity_aliases FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_relationships FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_relationship_sources FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_facts FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_fact_sources FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_conflicts FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_decisions FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_action_recommendations FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_nodes FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_edges FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_workflows FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_knowledge_gaps FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_learning_signals FORCE ROW LEVEL SECURITY",
    "ALTER TABLE graph_versions FORCE ROW LEVEL SECURITY",

    # RLS Policies
    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_domain_ontologies",
    "CREATE POLICY tenant_isolation_policy ON graph_domain_ontologies USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_entities",
    "CREATE POLICY tenant_isolation_policy ON graph_entities USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_entity_aliases",
    "CREATE POLICY tenant_isolation_policy ON graph_entity_aliases USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_relationships",
    "CREATE POLICY tenant_isolation_policy ON graph_relationships USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_relationship_sources",
    "CREATE POLICY tenant_isolation_policy ON graph_relationship_sources USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_facts",
    "CREATE POLICY tenant_isolation_policy ON graph_facts USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_fact_sources",
    "CREATE POLICY tenant_isolation_policy ON graph_fact_sources USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_conflicts",
    "CREATE POLICY tenant_isolation_policy ON graph_conflicts USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_decisions",
    "CREATE POLICY tenant_isolation_policy ON graph_decisions USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_action_recommendations",
    "CREATE POLICY tenant_isolation_policy ON graph_action_recommendations USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_nodes",
    "CREATE POLICY tenant_isolation_policy ON graph_nodes USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_edges",
    "CREATE POLICY tenant_isolation_policy ON graph_edges USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_workflows",
    "CREATE POLICY tenant_isolation_policy ON graph_workflows USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_knowledge_gaps",
    "CREATE POLICY tenant_isolation_policy ON graph_knowledge_gaps USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_learning_signals",
    "CREATE POLICY tenant_isolation_policy ON graph_learning_signals USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",

    "DROP POLICY IF EXISTS tenant_isolation_policy ON graph_versions",
    "CREATE POLICY tenant_isolation_policy ON graph_versions USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)"
]

async def run_migration():
    print("Running AWS RDS PostgreSQL Schema Migration for Module 3...")
    async with engine.begin() as conn:
        for stmt in TABLE_STATEMENTS:
            await conn.execute(text(stmt))
    print("[SUCCESS] AWS RDS PostgreSQL Module 3 Schema Migration Executed Successfully!")

if __name__ == "__main__":
    asyncio.run(run_migration())
