import asyncio
import uuid
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Force stdout to UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def test_postgres_rls():
    print("\n==========================================================================")
    print("        POSTGRESQL ROW-LEVEL SECURITY (RLS) DIRECT DB QUERY TEST          ")
    print("==========================================================================\n")

    tenant_alpha = str(uuid.uuid4())
    tenant_beta = str(uuid.uuid4())

    print(f"Tenant Alpha UUID: {tenant_alpha}")
    print(f"Tenant Beta UUID : {tenant_beta}\n")

    # Step 0: Ensure non-owner tenant_reader role exists
    async with async_session() as super_session:
        try:
            await super_session.execute(text("DROP ROLE IF EXISTS tenant_reader;"))
            await super_session.execute(text("CREATE ROLE tenant_reader WITH LOGIN PASSWORD 'tenant_password' NOBYPASSRLS;"))
            await super_session.execute(text("GRANT CONNECT ON DATABASE company_brain TO tenant_reader;"))
            await super_session.execute(text("GRANT USAGE ON SCHEMA public TO tenant_reader;"))
            await super_session.execute(text("GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO tenant_reader;"))
            await super_session.commit()
            print("[SETUP] Created non-owner 'tenant_reader' role with NOBYPASSRLS policy enforcement.")
        except Exception as ex:
            print(f"[SETUP ROLE NOTE] {ex}")
            await super_session.rollback()

    # Create engine for tenant_reader non-owner role
    reader_db_url = "postgresql+asyncpg://tenant_reader:tenant_password@localhost:5432/company_brain"
    app_engine = create_async_engine(reader_db_url, echo=False)
    app_session_factory = sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as super_session:
        try:
            await super_session.execute(text("ALTER TABLE documents ENABLE ROW LEVEL SECURITY;"))
            await super_session.execute(text("ALTER TABLE documents FORCE ROW LEVEL SECURITY;"))
            await super_session.execute(text("DROP POLICY IF EXISTS documents_tenant_isolation ON documents;"))
            await super_session.execute(text("""
                CREATE POLICY documents_tenant_isolation ON documents 
                FOR ALL TO PUBLIC 
                USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
            """))
            await super_session.commit()
            print("[SETUP] Enforced FOR ALL TO PUBLIC RLS policy on 'documents' table in PostgreSQL.")
        except Exception as ex:
            print(f"[SETUP ERROR Policy] {ex}")
            await super_session.rollback()

    # Step 1: Insert Tenant Alpha & Beta Records in tenants table
    async with app_session_factory() as session:
        try:
            await session.execute(
                text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT DO NOTHING"),
                {"id": tenant_alpha, "name": "Tenant Alpha Inc", "domain": f"alpha_{tenant_alpha[:8]}.com"}
            )
            await session.execute(
                text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT DO NOTHING"),
                {"id": tenant_beta, "name": "Tenant Beta Inc", "domain": f"beta_{tenant_beta[:8]}.com"}
            )
            await session.commit()
            print("[SETUP] Inserted Tenant Alpha and Tenant Beta records into 'tenants' table.")
        except Exception as ex:
            print(f"[SETUP ERROR Tenants] {ex}")
            await session.rollback()

    # Step 2: Insert Tenant Alpha Document Data
    async with app_session_factory() as session:
        try:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": tenant_alpha})
            await session.execute(
                text("""
                    INSERT INTO documents (tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key)
                    VALUES (:tenant_id, 'demo', 'doc', 'file', :ext_id, :title, :content, 'demo-bucket', 'alpha-key')
                """),
                {"tenant_id": tenant_alpha, "ext_id": f"ext_{tenant_alpha[:8]}", "title": "Alpha Roadmap", "content": "Project Sunrise launches in September"}
            )
            await session.commit()
            print("[INSERT] Ingested 'Project Sunrise' into Tenant Alpha.")
        except Exception as ex:
            print(f"[INSERT ERROR Alpha] {ex}")
            await session.rollback()

    # Step 3: Insert Tenant Beta Document Data
    async with app_session_factory() as session:
        try:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": tenant_beta})
            await session.execute(
                text("""
                    INSERT INTO documents (tenant_id, source_app, resource_category, resource_type, external_id, title, content, s3_bucket, s3_key)
                    VALUES (:tenant_id, 'demo', 'doc', 'file', :ext_id, :title, :content, 'demo-bucket', 'beta-key')
                """),
                {"tenant_id": tenant_beta, "ext_id": f"ext_{tenant_beta[:8]}", "title": "Beta Roadmap", "content": "Project Falcon launches in March"}
            )
            await session.commit()
            print("[INSERT] Ingested 'Project Falcon' into Tenant Beta.\n")
        except Exception as ex:
            print(f"[INSERT ERROR Beta] {ex}")
            await session.rollback()

    # Step 4: Query Project Falcon from Tenant Alpha Session (EXPECT: 0 rows)
    async with app_session_factory() as session:
        async with session.begin():
            print("--------------------------------------------------------------------------")
            print("TEST A: Querying 'Project Falcon' from TENANT ALPHA DB Session")
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": tenant_alpha})
            
            row_info = (await session.execute(text("SELECT current_user, usesuper FROM pg_user WHERE usename = current_user"))).fetchone()
            curr_user, is_super = row_info[0], row_info[1] if row_info else (None, None)
            curr_val = (await session.execute(text("SELECT current_setting('app.current_tenant_id', true)"))).scalar()
            print(f"[DEBUG] DB current_user = '{curr_user}' (Superuser = {is_super})")
            print(f"[DEBUG] DB current_setting('app.current_tenant_id') = '{curr_val}'")

            res = await session.execute(text("SELECT id, title, content FROM documents WHERE content ILIKE '%project falcon%'"))
            rows = res.fetchall()
            print(f"Executing: SELECT * FROM documents WHERE content ILIKE '%project falcon%'")
            print(f"Scoped Session tenant_id: '{tenant_alpha}'")
            print(f"Direct DB Query Result Row Count: {len(rows)} rows returned.")
            print(f"Rows Output: {rows}")
            if len(rows) == 0:
                print("RESULT: PASS - Zero rows returned across tenant boundary.")
            else:
                print("RESULT: FAIL - Leakage detected! Rows returned across boundary.")

    # Step 5: Query Project Falcon from Tenant Beta Session (EXPECT: 1 row)
    async with app_session_factory() as session:
        async with session.begin():
            print("\n--------------------------------------------------------------------------")
            print("TEST B: Querying 'Project Falcon' from TENANT BETA DB Session")
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": tenant_beta})
            res = await session.execute(text("SELECT id, title, content FROM documents WHERE content ILIKE '%project falcon%'"))
            rows = res.fetchall()
            print(f"Executing: SELECT * FROM documents WHERE content ILIKE '%project falcon%'")
            print(f"Scoped Session tenant_id: '{tenant_beta}'")
            print(f"Direct DB Query Result Row Count: {len(rows)} rows returned.")
            print(f"Rows Output: {rows}")
            if len(rows) >= 1:
                print("RESULT: PASS - Authorized data returned cleanly for Tenant Beta.")
            else:
                print("RESULT: FAIL - Authorized data missing!")
            print("--------------------------------------------------------------------------\n")

if __name__ == "__main__":
    asyncio.run(test_postgres_rls())
