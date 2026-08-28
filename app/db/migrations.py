from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.base import Base

SCHEMA_VERSION = 3
LEGACY_TABLES = frozenset({"media", "users"})
EXPECTED_TABLES = frozenset(
    {
        "broadcast_recipients",
        "broadcasts",
        "channels",
        "content_options",
        "option_content_items",
        "users",
    }
)
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
            "is_reachable",
            "unreachable_at",
            "created_at",
            "updated_at",
        }
    ),
    "channels": frozenset(
        {"id", "telegram_chat_id", "title", "join_url", "created_at", "updated_at"}
    ),
    "content_options": frozenset(
        {
            "id",
            "name_uz",
            "name_ru",
            "name_en",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        }
    ),
    "option_content_items": frozenset(
        {
            "id",
            "option_id",
            "telegram_file_id",
            "telegram_file_unique_id",
            "media_type",
            "original_filename",
            "text_uz",
            "text_ru",
            "text_en",
            "sort_order",
            "created_at",
            "updated_at",
        }
    ),
    "broadcasts": frozenset(
        {
            "id",
            "request_token",
            "admin_telegram_id",
            "admin_language",
            "media_type",
            "telegram_file_id",
            "telegram_file_unique_id",
            "original_filename",
            "text_uz",
            "text_ru",
            "text_en",
            "status",
            "cancellation_requested",
            "created_at",
            "started_at",
            "finished_at",
        }
    ),
    "broadcast_recipients": frozenset(
        {
            "id",
            "broadcast_id",
            "telegram_id",
            "language_code",
            "status",
            "attempt_count",
            "next_attempt_at",
            "last_error",
            "sent_at",
            "created_at",
            "updated_at",
        }
    ),
}

V2_EXPECTED_COLUMNS = {
    "users": EXPECTED_COLUMNS["users"],
    "channels": EXPECTED_COLUMNS["channels"],
    "media": frozenset(
        {
            "id",
            "telegram_file_id",
            "telegram_file_unique_id",
            "media_type",
            "original_filename",
            "caption",
            "text_uz",
            "text_ru",
            "text_en",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        }
    ),
    "broadcasts": EXPECTED_COLUMNS["broadcasts"],
    "broadcast_recipients": EXPECTED_COLUMNS["broadcast_recipients"],
}

V1_EXPECTED_COLUMNS = {
    "users": V2_EXPECTED_COLUMNS["users"] - {"is_reachable", "unreachable_at"},
    "channels": V2_EXPECTED_COLUMNS["channels"],
    "media": V2_EXPECTED_COLUMNS["media"] - {"text_uz", "text_ru", "text_en"},
}
KNOWN_TABLES = frozenset(EXPECTED_COLUMNS) | frozenset(V2_EXPECTED_COLUMNS)


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


async def _validate_columns(
    connection: AsyncConnection, expected: dict[str, frozenset[str]]
) -> None:
    tables = await _table_names(connection)
    missing_tables = set(expected) - tables
    if missing_tables:
        raise SchemaMigrationError(
            f"database schema is missing tables: {', '.join(sorted(missing_tables))}"
        )
    for table, expected_columns in expected.items():
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
    app_tables = tables & KNOWN_TABLES
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
        await connection.exec_driver_sql("PRAGMA user_version=1")
        version = 1

    if version == 1:
        await _validate_columns(connection, V1_EXPECTED_COLUMNS)
        user_columns = await _column_names(connection, "users")
        if "is_reachable" not in user_columns:
            await connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN is_reachable BOOLEAN NOT NULL DEFAULT 1"
            )
        if "unreachable_at" not in user_columns:
            await connection.exec_driver_sql("ALTER TABLE users ADD COLUMN unreachable_at DATETIME")

        media_columns = await _column_names(connection, "media")
        for column in ("text_uz", "text_ru", "text_en"):
            if column not in media_columns:
                await connection.exec_driver_sql(f'ALTER TABLE media ADD COLUMN "{column}" TEXT')
        await connection.exec_driver_sql(
            "UPDATE media SET "
            "text_uz = COALESCE(text_uz, caption), "
            "text_ru = COALESCE(text_ru, caption), "
            "text_en = COALESCE(text_en, caption)"
        )
        await connection.run_sync(
            lambda sync_connection: Base.metadata.tables["broadcasts"].create(
                sync_connection, checkfirst=True
            )
        )
        await connection.run_sync(
            lambda sync_connection: Base.metadata.tables["broadcast_recipients"].create(
                sync_connection, checkfirst=True
            )
        )
        await connection.exec_driver_sql("PRAGMA user_version=2")
        version = 2

    if version == 2:
        await _validate_columns(connection, V2_EXPECTED_COLUMNS)
        await connection.run_sync(
            lambda sync_connection: Base.metadata.tables["content_options"].create(
                sync_connection, checkfirst=True
            )
        )
        await connection.run_sync(
            lambda sync_connection: Base.metadata.tables["option_content_items"].create(
                sync_connection, checkfirst=True
            )
        )
        legacy_count = int(
            (await connection.exec_driver_sql("SELECT COUNT(*) FROM media")).scalar_one()
        )
        if legacy_count:
            insert_result = await connection.exec_driver_sql(
                "INSERT INTO content_options ("
                "name_uz, name_ru, name_en, is_active, sort_order, created_at, updated_at"
                ") VALUES ("
                "'Import qilingan kontent', 'Импортированный контент', "
                "'Imported content', 0, 10, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
                ")"
            )
            imported_option_id = int(insert_result.lastrowid)
            await connection.exec_driver_sql(
                "INSERT INTO option_content_items ("
                "option_id, telegram_file_id, telegram_file_unique_id, media_type, "
                "original_filename, text_uz, text_ru, text_en, sort_order, "
                "created_at, updated_at"
                ") SELECT ?, telegram_file_id, telegram_file_unique_id, media_type, "
                "original_filename, "
                "COALESCE(NULLIF(text_uz, ''), NULLIF(caption, ''), "
                "'Import qilingan kontent'), "
                "COALESCE(NULLIF(text_ru, ''), NULLIF(caption, ''), "
                "'Импортированный контент'), "
                "COALESCE(NULLIF(text_en, ''), NULLIF(caption, ''), "
                "'Imported content'), "
                "sort_order, created_at, updated_at FROM media ORDER BY sort_order, id",
                (imported_option_id,),
            )
        await connection.exec_driver_sql("DROP TABLE media")
        await connection.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")

    await _validate_current_schema(connection)
