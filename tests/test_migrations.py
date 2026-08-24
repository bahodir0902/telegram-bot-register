import sqlite3

import pytest

from app.db.migrations import SCHEMA_VERSION, SchemaMigrationError
from app.db.session import create_database
from app.health import check_database


async def test_legacy_database_is_upgraded_without_losing_data(tmp_path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                telegram_id BIGINT NOT NULL UNIQUE,
                phone_number VARCHAR(32),
                username VARCHAR(64),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                phone_verified_at DATETIME,
                subscription_verified_at DATETIME,
                subscription_prompt_message_id BIGINT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE media (
                id INTEGER PRIMARY KEY,
                telegram_file_id VARCHAR(512) NOT NULL,
                telegram_file_unique_id VARCHAR(255),
                media_type VARCHAR(20) NOT NULL,
                original_filename VARCHAR(255),
                caption TEXT,
                is_active BOOLEAN NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            INSERT INTO users (
                id, telegram_id, created_at, updated_at
            ) VALUES (1, 42, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            """
        )

    database = create_database(database_path)
    await database.initialize()
    await database.close()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT telegram_id FROM users").fetchone()[0] == 42
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
        assert "language_code" in columns
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='channels'"
        ).fetchone()
    check_database(database_path)


async def test_future_database_schema_is_rejected(tmp_path) -> None:
    database_path = tmp_path / "future.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")

    database = create_database(database_path)
    with pytest.raises(SchemaMigrationError, match="newer"):
        await database.initialize()
    await database.close()
