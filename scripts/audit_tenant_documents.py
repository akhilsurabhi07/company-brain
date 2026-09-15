import asyncio
import sys

sys.path.insert(0, "C:/Users/Surabhi Akhil/OneDrive/Desktop/PCB")
sys.path.insert(0, "C:/Users/Surabhi Akhil/.gemini/antigravity/brain/82259030-8311-4a5c-af32-71cedbfe5073")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text
from app.db.database import async_session_factory

async def audit_tenant_db():
    tenant_id = "00000000-0000-0000-0000-000000000001"
    print(f"\n==========================================================================")
    print(f" 🔍 AUDITING DATABASE DOCUMENTS & CHUNKS FOR TENANT: {tenant_id}")
    print(f"==========================================================================")

    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": tenant_id}
        )

        res_docs = await session.execute(
            text("""
                SELECT id, source_app, resource_category, resource_type, external_id, title
                FROM documents
                WHERE tenant_id = :tid
                ORDER BY source_app, title
            """),
            {"tid": tenant_id}
        )
        docs = res_docs.fetchall()
        print(f"\n📄 TOTAL DOCUMENTS IN TENANT: {len(docs)}")
        for d in docs:
            print(f"  • [{d.source_app.upper()}] '{d.title}' (ID: {d.id})")

        res_chunks = await session.execute(
            text("""
                SELECT count(*) FROM document_chunks WHERE tenant_id = :tid
            """),
            {"tid": tenant_id}
        )
        chunk_count = res_chunks.scalar()
        print(f"\n🧩 TOTAL PARENT-CHILD CHUNKS IN TENANT: {chunk_count}")
        print("==========================================================================\n")

if __name__ == "__main__":
    asyncio.run(audit_tenant_db())
