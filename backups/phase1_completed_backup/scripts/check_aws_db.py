import os
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.config import settings

async def check_database_contents():
    print("\n=======================================================")
    print(f"Inspecting AWS RDS PostgreSQL Database:")
    print(f"Host: {settings.POSTGRES_HOST}")
    print("=======================================================\n")

    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        # 1. List all tables
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """))
        tables = [row[0] for row in result.fetchall()]
        print(f"TABLES FOUND IN DATABASE ({len(tables)} tables):")
        for table in tables:
            print(f"   * {table}")
        print()

        # 2. Inspect Tenants
        res_tenants = await conn.execute(text("SELECT id, name, domain, created_at FROM tenants;"))
        tenants = res_tenants.fetchall()
        print(f"TENANTS ({len(tenants)} entries):")
        for t in tenants:
            print(f"   * ID: {t[0]} | Name: {t[1]} | Domain: {t[2]}")
        print()

        # 3. Inspect Documents & S3 Pointers (Set RLS context)
        tenant_id = "00000000-0000-0000-0000-000000000001"
        await conn.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
        
        res_docs = await conn.execute(text("""
            SELECT source_app, resource_category, title, s3_bucket, s3_key, file_size_bytes 
            FROM documents;
        """))
        docs = res_docs.fetchall()
        print(f"DOCUMENTS & S3 POINTERS ({len(docs)} entries):")
        for d in docs:
            print(f"   * App: {d[0].upper()} | Category: {d[1]}")
            print(f"     Title: '{d[2]}'")
            print(f"     S3 Bucket: {d[3]}")
            print(f"     S3 Key: {d[4]} ({d[5]} bytes)")
            print()

    print("=======================================================")
    print("DATABASE CHECK COMPLETE!")
    print("=======================================================\n")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_database_contents())
