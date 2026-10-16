"""
Async SQLAlchemy engine/session setup. This is the ONLY place the engine
is constructed — request handlers get a session via the `get_db`
dependency in app/api/deps.py; background code uses `AsyncSessionLocal`.

Schema changes go through Alembic (`migrations/`), never `create_all`
in the running service.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

_connect_args = {"ssl": True} if settings.database_requires_ssl else {}

engine = create_async_engine(
    settings.async_database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass
