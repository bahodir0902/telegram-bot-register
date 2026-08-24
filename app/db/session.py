from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Importing models registers ORM tables on Base.metadata before schema initialization.
from app.db import models as _models  # noqa: F401
from app.db.migrations import migrate_schema

AsyncSessionFactory = async_sessionmaker[AsyncSession]


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(dbapi_connection: Any, _connection_record: Any) -> None:
    """Apply safe, small-application SQLite defaults to each connection."""

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


@dataclass(slots=True)
class Database:
    engine: AsyncEngine
    session_factory: AsyncSessionFactory

    async def initialize(self) -> None:
        async with self.engine.connect() as connection:
            await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            await connection.commit()
        async with self.engine.begin() as connection:
            await migrate_schema(connection)

    async def close(self) -> None:
        await self.engine.dispose()


def create_database(path: Path) -> Database:
    resolved_path = path.resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{resolved_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return Database(engine=engine, session_factory=session_factory)
