import contextlib
from typing import AsyncGenerator
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.sql import text
from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

@contextlib.asynccontextmanager
async def get_tenant_session(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager providing a SQLAlchemy session with Row Level Security (RLS)
    scoped strictly to the given tenant_id.
    """
    async with async_session_factory() as session:
        # Set the local session variable for RLS policies
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

async def init_db_schema(schema_sql_path: str = "app/db/schema.sql") -> None:
    """
    Utility function to initialize the database tables from schema.sql.
    """
    with open(schema_sql_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    async with engine.begin() as conn:
        await conn.execute(text(schema_sql))
