import os
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings

async def init_aws_rds():
    print(f"\n=======================================================")
    print(f"Connecting to AWS RDS PostgreSQL Database:")
    print(f"Host: {settings.POSTGRES_HOST}")
    print(f"=======================================================\n")

    # Create async engine
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    # Read schema.sql
    schema_path = os.path.join(os.path.dirname(__file__), "..", "app", "db", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    print("Executing database schema initialization (Tables, Indexes, RLS Policies)...")
    
    # Split schema statements by semicolon for asyncpg
    statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

    async with engine.begin() as conn:
        for stmt in statements:
            # Skip pure comments or empty strings
            if stmt.startswith("--") and "\n" not in stmt:
                continue
            await conn.execute(text(stmt))

    print("Database tables & RLS policies created successfully!")

    # Insert test tenant & sample document records
    async with engine.begin() as conn:
        tenant_id = "00000000-0000-0000-0000-000000000001"

        # Check if tenant exists
        res = await conn.execute(text(f"SELECT id FROM tenants WHERE id = '{tenant_id}'"))
        if not res.fetchone():
            await conn.execute(text(f"""
                INSERT INTO tenants (id, name, domain) 
                VALUES ('{tenant_id}', 'Acme Corp', 'acme.com')
            """))

        # Enable RLS context for session
        await conn.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))

        # Insert test document pointing to S3
        await conn.execute(text(f"""
            INSERT INTO documents (
                tenant_id, source_app, resource_category, resource_type, external_id,
                title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
            ) VALUES (
                '{tenant_id}', 'slack', 'chat_message', 'message', 'slack_msg_1001',
                'Welcome to Company Brain AWS Test', 'Extracted message text from Slack channel #general',
                'company-brain-raw-data-vault', 'raw/tenant_acme_corp/slack/message/slack_msg_1001.json.zst',
                TRUE, 112
            ) ON CONFLICT (tenant_id, source_app, external_id) DO NOTHING
        """))

    print("\n=======================================================")
    print("SUCCESS! AWS RDS Database Schema initialized & test data inserted.")
    print("=======================================================\n")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(init_aws_rds())
