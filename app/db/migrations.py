from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.base import Base

SCHEMA_VERSION = 1
LEGACY_TABLES = frozenset({"media", "users"})
EXPECTED_TABLES = frozenset({"channels", "media", "users"})
EXPECTED_COLUMNS = {
    "users": frozenset(
        {
            "id",
            "telegram_id",
            "phone_number",
            "username",
            "first_name",
            "last_name",
            "language_code",
            "phone_verified_at",
            "subscription_verified_at",
            "subscription_prompt_message_id",
            "created_at",
            "updated_at",
        }
    ),
    "channels": frozenset(
        {"id", "telegram_chat_id", "title", "join_url", "created_at", "updated_at"}
    ),
    "media": frozenset(
        {
            "id",
            "telegram_file_id",
            "telegram_file_unique_id",
            "media_type",
            "original_filename",
            "caption",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        }
    ),
}


class SchemaMigrationError(RuntimeError):
    """The SQLite schema cannot be safely migrated by this application version."""


async def _table_names(connection: AsyncConnection) -> set[str]:
    result = await connection.execute(
        text("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    )
    return {str(row[0]) for row in result}


async def _column_names(connection: AsyncConnection, table: str) -> set[str]:
    result = await connection.exec_driver_sql(f'PRAGMA table_info("{table}")')
    return {str(row[1]) for row in result}


async def _validate_current_schema(connection: AsyncConnection) -> None:
    tables = await _table_names(connection)
    missing = EXPECTED_TABLES - tables
    if missing:
        raise SchemaMigrationError(
            f"database schema is missing tables: {', '.join(sorted(missing))}"
        )
    for table, expected_columns in EXPECTED_COLUMNS.items():
        columns = await _column_names(connection, table)
        missing_columns = expected_columns - columns
        if missing_columns:
            raise SchemaMigrationError(
                f"database table {table} is missing columns: {', '.join(sorted(missing_columns))}"
            )


async def migrate_schema(connection: AsyncConnection) -> None:
    version = int((await connection.exec_driver_sql("PRAGMA user_version")).scalar_one())
    if version > SCHEMA_VERSION:
        raise SchemaMigrationError(
            f"database schema version {version} is newer than supported version {SCHEMA_VERSION}"
        )

    tables = await _table_names(connection)
    app_tables = tables & EXPECTED_TABLES
    if not app_tables:
        await connection.run_sync(Base.metadata.create_all)
        await connection.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
        await _validate_current_schema(connection)
        return

    if version == 0:
        if not LEGACY_TABLES.issubset(tables):
            missing = LEGACY_TABLES - tables
            raise SchemaMigrationError(
                f"legacy database schema is missing tables: {', '.join(sorted(missing))}"
            )
        user_columns = await _column_names(connection, "users")
        if "language_code" not in user_columns:
            await connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN language_code VARCHAR(2) "
                "CHECK (language_code IN ('uz', 'ru', 'en'))"
            )
        await connection.run_sync(
            lambda sync_connection: Base.metadata.tables["channels"].create(
                sync_connection, checkfirst=True
            )
        )
        await connection.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")

    await _validate_current_schema(connection)
