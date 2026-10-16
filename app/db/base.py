"""
Async SQLAlchemy engine/session setup. This is the ONLY place engines are
constructed — request handlers get a session via the `get_db` dependency
in app/api/deps.py; background code uses `AsyncSessionLocal`.

Schema changes go through Alembic (`migrations/`), never `create_all`
in the running service.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import is_pgbouncer, requires_ssl, settings


def make_engine(raw_url: str, async_url: str) -> AsyncEngine:
    connect_args: dict = {}
    if requires_ssl(raw_url):
        connect_args["ssl"] = True
    if is_pgbouncer(raw_url):
        # Neon's pooled endpoint is PgBouncer in transaction mode: a session
        # can land on a different server connection per transaction, so
        # asyncpg's statement cache must be off and prepared statements need
        # unique names (SQLAlchemy's documented PgBouncer setup).
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid.uuid4()}__"
    return create_async_engine(
        async_url,
        echo=False,
        # Neon scales compute to zero when idle, which drops open connections.
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args=connect_args,
    )


engine = make_engine(settings.database_url, settings.async_database_url)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass
