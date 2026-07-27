import os
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import boto3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.config import settings
from app.storage.compressor import zstd_compressor

async def ingest_multi_company_demo():
    print("\n=======================================================")
    print("Multi-Tenant Demonstration: Ingesting Data for 3 Companies")
    print("Company 1: Acme Corp   (tenant_acme_111)")
    print("Company 2: Tesla Motors (tenant_tesla_222)")
    print("Company 3: Nike Sport  (tenant_nike_333)")
    print("=======================================================\n")

    # AWS S3 Client
    s3_client = boto3.client(
        "s3",
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
    )

    # Database Engine
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    companies = [
        {
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "folder_id": "tenant_acme_111",
            "name": "Acme Corp",
            "domain": "acme.com",
            "app": "slack",
            "category": "chat_message",
            "ext_id": "msg_acme_101",
            "title": "Acme Q3 Sales Meeting Notes",
            "content": "Discussing Acme Q3 revenue targets.",
            "payload": {"text": "Discussing Acme Q3 revenue targets.", "user": "alice_acme"}
        },
        {
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "folder_id": "tenant_tesla_222",
            "name": "Tesla Motors",
            "domain": "tesla.com",
            "app": "github",
            "category": "code_pr",
            "ext_id": "pr_tesla_202",
            "title": "PR #99: Autopilot Neural Network Optimization",
            "content": "Optimizing vision perception models for Cybertruck.",
            "payload": {"pr": 99, "title": "Autopilot Neural Network Optimization", "user": "elon_tesla"}
        },
        {
            "tenant_id": "00000000-0000-0000-0000-000000000003",
            "folder_id": "tenant_nike_333",
            "name": "Nike Sport",
            "domain": "nike.com",
            "app": "google_drive",
            "category": "doc",
            "ext_id": "file_nike_303",
            "title": "Air Max 2026 Marketing Strategy.pdf",
            "content": "Global campaign strategy for Air Max 2026 launch.",
            "payload": {"file": "Air Max 2026 Marketing Strategy.pdf", "owner": "marketer_nike"}
        }
    ]

    for comp in companies:
        tenant_uuid = comp["tenant_id"]
        folder_id = comp["folder_id"]
        app = comp["app"]
        ext_id = comp["ext_id"]

        print(f"Ingesting for {comp['name']} ({comp['domain']})...")

        # 1. Upload Zstd compressed JSON payload to AWS S3 in tenant folder
        zstd_bytes = zstd_compressor.compress_json(comp["payload"])
        s3_key = f"raw/{folder_id}/{app}/{comp['category']}/{ext_id}.json.zst"

        s3_client.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            Body=zstd_bytes,
            ContentType="application/zstd",
            Metadata={"tenant_id": tenant_uuid, "source_app": app}
        )
        print(f"   [AWS S3] Uploaded: s3://{settings.S3_BUCKET_NAME}/{s3_key}")

        # 2. Save metadata to AWS RDS PostgreSQL
        async with engine.begin() as conn:
            # Upsert Tenant
            await conn.execute(text(f"""
                INSERT INTO tenants (id, name, domain) 
                VALUES ('{tenant_uuid}', '{comp['name']}', '{comp['domain']}')
                ON CONFLICT (id) DO NOTHING;
            """))

            # Set session RLS tenant context
            await conn.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_uuid}'"))

            # Upsert Document Metadata
            await conn.execute(text(f"""
                INSERT INTO documents (
                    tenant_id, source_app, resource_category, resource_type, external_id,
                    title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                ) VALUES (
                    '{tenant_uuid}', '{app}', '{comp['category']}', 'file', '{ext_id}',
                    '{comp['title']}', '{comp['content']}', '{settings.S3_BUCKET_NAME}', '{s3_key}',
                    TRUE, {len(zstd_bytes)}
                ) ON CONFLICT (tenant_id, source_app, external_id) DO NOTHING;
            """))
            print(f"   [AWS RDS] Saved row in PostgreSQL documents table with RLS tenant_id='{tenant_uuid}'\n")

    print("=======================================================")
    print("DEMO COMPLETE! All 3 companies ingested into AWS S3 & RDS.")
    print("=======================================================\n")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(ingest_multi_company_demo())
