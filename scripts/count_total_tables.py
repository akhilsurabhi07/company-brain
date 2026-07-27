import asyncio
from sqlalchemy import text
from app.db.database import async_session_factory

async def count_total_tables():
    async with async_session_factory() as session:
        res = await session.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """))
        tables = [r[0] for r in res.fetchall()]
        print("======================================================================")
        print(f"  TOTAL TABLES IN AWS RDS POSTGRESQL DATABASE : {len(tables)}")
        print("======================================================================\n")
        for idx, t in enumerate(tables, 1):
            print(f"  {idx:2d}. {t}")
        print("======================================================================")

if __name__ == "__main__":
    asyncio.run(count_total_tables())
