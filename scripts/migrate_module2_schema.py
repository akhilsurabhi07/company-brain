"""
Module 2 Database Schema Migration Script — AWS RDS PostgreSQL
===============================================================
Adds columns to document_chunks and embeddings tables.
"""
import asyncio
from sqlalchemy import text
from app.db.database import async_session_factory

async def run_schema_migration():
    print("======================================================================")
    print("      APPLYING MODULE 2 SCHEMA MIGRATION TO AWS RDS POSTGRESQL")
    print("======================================================================\n")

    migrations = [
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS parent_chunk_id VARCHAR(255);",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS char_count INTEGER DEFAULT 0;",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS checksum VARCHAR(64);",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS language_code VARCHAR(10) DEFAULT 'en';",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS structural_score DOUBLE PRECISION DEFAULT 1.0;",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS semantic_score DOUBLE PRECISION DEFAULT 1.0;",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS business_score DOUBLE PRECISION DEFAULT 1.0;",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS importance_score DOUBLE PRECISION DEFAULT 1.0;",
        "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES documents(id) ON DELETE CASCADE;",
        "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS checksum VARCHAR(64);",
    ]

    async with async_session_factory() as session:
        for stmt in migrations:
            print(f"  Executing: {stmt}")
            await session.execute(text(stmt))
        await session.commit()

    print("\n======================================================================")
    print("  [SUCCESS] SCHEMA MIGRATION APPLIED TO AWS RDS POSTGRESQL!")
    print("======================================================================")

if __name__ == "__main__":
    asyncio.run(run_schema_migration())
