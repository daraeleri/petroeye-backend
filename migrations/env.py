"""Alembic environment. The database URL comes from app settings, never
from alembic.ini: DATABASE_URL_UNPOOLED (Neon direct endpoint) when set,
otherwise DATABASE_URL. Migrations must not run through PgBouncer."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.db import models  # noqa: F401  (registers all tables on Base.metadata)
from app.config import settings
from app.db.base import Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.async_migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = make_engine(settings.database_url_unpooled or settings.database_url, settings.async_migration_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
