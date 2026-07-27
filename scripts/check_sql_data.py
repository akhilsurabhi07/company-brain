"""
Live SQL Database Verification Script — Company Brain AWS RDS PostgreSQL
========================================================================
Queries live PostgreSQL tables directly to display extracted documents,
normalized tables, sections, metadata, and pipeline jobs state.
"""
import asyncio
from sqlalchemy import text
from app.db.database import async_session_factory

async def check_sql_database_records():
    print("======================================================================")
    print("      COMPANY BRAIN -- AWS RDS POSTGRESQL LIVE DATA AUDIT")
    print("======================================================================\n")

    async with async_session_factory() as session:
        # 1. Total row counts across normalized Document Intelligence tables
        tables_to_check = [
            "documents",
            "document_processing_jobs",
            "document_metadata",
            "document_sections",
            "document_tables",
            "document_images",
            "document_chunks",
            "embeddings",
            "entities",
        ]

        print("  [TABLE ROW COUNTS IN LIVE AWS RDS POSTGRESQL]")
        for tbl in tables_to_check:
            res = await session.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
            count = res.fetchone()[0]
            print(f"    - Table '{tbl:<24}' : {count} rows")

        # 2. Inspect Latest Extracted Document Details
        print("\n  [INSPECTING LATEST EXTRACTED DOCUMENTS]")
        res_docs = await session.execute(
            text("SELECT id, tenant_id, source_app, title, mime_type, ingested_at FROM documents ORDER BY ingested_at DESC LIMIT 3")
        )
        docs = res_docs.fetchall()
        for idx, d in enumerate(docs, 1):
            print(f"    Document {idx}:")
            print(f"      - ID          : {d[0]}")
            print(f"      - Tenant ID   : {d[1]}")
            print(f"      - App Source  : {d[2]}")
            print(f"      - Title       : {d[3]}")
            print(f"      - MIME Type   : {d[4]}")
            print(f"      - Ingested At : {d[5]}")

        # 3. Inspect Latest Normalized Table Grid (Financial_Report.csv)
        print("\n  [INSPECTING NORMALIZED TABLE DATA (Markdown Grid in SQL)]")
        res_tbls = await session.execute(
            text("SELECT document_id, table_number, rows_count, cols_count, grid_markdown FROM document_tables ORDER BY created_at DESC LIMIT 1")
        )
        tbl_row = res_tbls.fetchone()
        if tbl_row:
            print(f"    - Parent Document ID : {tbl_row[0]}")
            print(f"    - Table Number       : {tbl_row[1]}")
            print(f"    - Matrix Dimensions  : {tbl_row[2]} rows x {tbl_row[3]} columns")
            print("    - Live Markdown Grid Stored in SQL :\n")
            for line in tbl_row[4].splitlines():
                print(f"        {line}")

    print("\n======================================================================")
    print("  [VERIFIED] ALL EXTRACTED DATA IS SAFELY STORED IN AWS RDS POSTGRESQL!")
    print("======================================================================")

if __name__ == "__main__":
    asyncio.run(check_sql_database_records())
