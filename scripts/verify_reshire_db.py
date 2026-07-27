import asyncio
from sqlalchemy import text
from app.db.database import async_session_factory

async def inspect_tenant_storage():
    async with async_session_factory() as session:
        # Find tenant ID for reshire.in
        res_tenant = await session.execute(
            text("SELECT id, name, domain FROM tenants WHERE domain = 'reshire.in'")
        )
        tenant = res_tenant.fetchone()
        if not tenant:
            print("No tenant found for reshire.in")
            return

        tenant_id, name, domain = str(tenant[0]), tenant[1], tenant[2]
        print("=======================================================")
        print(f"TENANT VERIFICATION: {name} ({domain})")
        print(f"Tenant UUID: {tenant_id}")
        print("=======================================================")

        # Query SQL database documents table
        res_docs = await session.execute(
            text("""
                SELECT source_app, resource_type, external_id, title, file_size_bytes, s3_bucket, s3_key, ingested_at
                FROM documents
                WHERE tenant_id = :tenant_id
                ORDER BY ingested_at DESC
            """),
            {"tenant_id": tenant_id},
        )
        rows = res_docs.fetchall()
        print(f"\n[PostgreSQL AWS RDS Verification] Total Rows Stored: {len(rows)}")
        print("-" * 75)
        for r in rows:
            print(f"App: {r[0]:<12} | Type: {r[1]:<12} | Title: {r[3]}")
            print(f"  -> S3 Bucket: {r[5]}")
            print(f"  -> S3 Key:    {r[6]}")
            print(f"  -> File Size: {r[4]} Bytes")
            print("-" * 75)

        # Query sync_statuses table
        res_statuses = await session.execute(
            text("""
                SELECT source_app, status, total_items_synced, error_message
                FROM sync_statuses
                WHERE tenant_id = :tenant_id
            """),
            {"tenant_id": tenant_id},
        )
        print("\n[SQL Sync Status Table Breakdown]")
        print("-" * 55)
        for s in res_statuses.fetchall():
            err_str = s[3] if s[3] else "None"
            print(f"App: {s[0]:<12} | Status: {s[1]:<10} | Synced: {s[2]} items | Error: {err_str}")

if __name__ == "__main__":
    asyncio.run(inspect_tenant_storage())
