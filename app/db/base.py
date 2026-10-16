"""
Async SQLAlchemy engine/session setup. This is the ONLY place the engine
is constructed — everything else gets a session via the `get_db` dependency
in app/api/deps.py.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """
    Creates tables from the current models if they don't exist.

    This is a convenience for early development only. Once the schema
    stabilizes, switch to real Alembic migrations (see alembic/ — scaffold
    it with `alembic init alembic` and generate the first revision from
    these models) instead of relying on create_all in production.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
