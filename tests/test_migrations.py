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
            INSERT INTO media (
                id, telegram_file_id, media_type, caption, is_active, sort_order,
                created_at, updated_at
            ) VALUES (
                1, 'legacy-file', 'photo', 'Legacy caption', 1, 10,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
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
        assert {"is_reachable", "unreachable_at"}.issubset(columns)
        assert {
            "first_started_at",
            "last_started_at",
            "first_start_source",
            "last_start_source",
        }.issubset(columns)
        assert not connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='media'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='channels'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='broadcasts'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='broadcast_recipients'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='content_options'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='option_content_items'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='video_lessons'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='video_lesson_videos'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='engagement_events'"
        ).fetchone()
        imported = connection.execute("SELECT name_en, is_active FROM content_options").fetchone()
        assert imported == ("Imported content", 0)
        imported_item = connection.execute(
            "SELECT telegram_file_id, media_type, text_uz, text_ru, text_en, sort_order "
            "FROM option_content_items"
        ).fetchone()
        assert imported_item == (
            "legacy-file",
            "photo",
            "Legacy caption",
            "Legacy caption",
            "Legacy caption",
            10,
        )
    check_database(database_path)


async def test_future_database_schema_is_rejected(tmp_path) -> None:
    database_path = tmp_path / "future.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")

    database = create_database(database_path)
    with pytest.raises(SchemaMigrationError, match="newer"):
        await database.initialize()
    await database.close()


async def test_version_one_database_is_upgraded_in_place(tmp_path) -> None:
    database_path = tmp_path / "version-one.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA user_version=1;
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                telegram_id BIGINT NOT NULL UNIQUE,
                phone_number VARCHAR(32),
                username VARCHAR(64),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                language_code VARCHAR(2),
                phone_verified_at DATETIME,
                subscription_verified_at DATETIME,
                subscription_prompt_message_id BIGINT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY,
                telegram_chat_id VARCHAR(64) NOT NULL UNIQUE,
                title VARCHAR(255) NOT NULL,
                join_url VARCHAR(512) NOT NULL,
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
            INSERT INTO media (
                id, telegram_file_id, media_type, caption, is_active, sort_order,
                created_at, updated_at
            ) VALUES (
                7, 'file-id', 'document', 'Kept', 1, 10,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            """
        )

    database = create_database(database_path)
    await database.initialize()
    await database.close()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert not connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='media'"
        ).fetchone()
        assert connection.execute("SELECT name_en, is_active FROM content_options").fetchone() == (
            "Imported content",
            0,
        )
        assert connection.execute(
            "SELECT telegram_file_id, media_type, text_en FROM option_content_items"
        ).fetchone() == ("file-id", "document", "Kept")
    check_database(database_path)


async def test_version_two_database_imports_global_library_and_preserves_broadcasts(
    tmp_path,
) -> None:
    database_path = tmp_path / "version-two.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA user_version=2;
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, telegram_id BIGINT NOT NULL UNIQUE,
                phone_number VARCHAR(32), username VARCHAR(64), first_name VARCHAR(255),
                last_name VARCHAR(255), language_code VARCHAR(2), phone_verified_at DATETIME,
                subscription_verified_at DATETIME, subscription_prompt_message_id BIGINT,
                is_reachable BOOLEAN NOT NULL, unreachable_at DATETIME,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            );
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY, telegram_chat_id VARCHAR(64) NOT NULL UNIQUE,
                title VARCHAR(255) NOT NULL, join_url VARCHAR(512) NOT NULL,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            );
            CREATE TABLE media (
                id INTEGER PRIMARY KEY, telegram_file_id VARCHAR(512) NOT NULL,
                telegram_file_unique_id VARCHAR(255), media_type VARCHAR(20) NOT NULL,
                original_filename VARCHAR(255), caption TEXT, text_uz TEXT, text_ru TEXT,
                text_en TEXT, is_active BOOLEAN NOT NULL, sort_order INTEGER NOT NULL,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            );
            CREATE TABLE broadcasts (
                id INTEGER PRIMARY KEY, request_token VARCHAR(64) NOT NULL UNIQUE,
                admin_telegram_id BIGINT NOT NULL, admin_language VARCHAR(2) NOT NULL,
                media_type VARCHAR(20) NOT NULL, telegram_file_id VARCHAR(512) NOT NULL,
                telegram_file_unique_id VARCHAR(255), original_filename VARCHAR(255),
                text_uz TEXT NOT NULL, text_ru TEXT NOT NULL, text_en TEXT NOT NULL,
                status VARCHAR(20) NOT NULL, cancellation_requested BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL, started_at DATETIME, finished_at DATETIME
            );
            CREATE TABLE broadcast_recipients (
                id INTEGER PRIMARY KEY, broadcast_id INTEGER NOT NULL,
                telegram_id BIGINT NOT NULL, language_code VARCHAR(2) NOT NULL,
                status VARCHAR(20) NOT NULL, attempt_count INTEGER NOT NULL,
                next_attempt_at DATETIME, last_error TEXT, sent_at DATETIME,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            );
            INSERT INTO users (
                id, telegram_id, is_reachable, created_at, updated_at
            ) VALUES (1, 42, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            INSERT INTO media (
                id, telegram_file_id, media_type, text_uz, text_ru, text_en,
                is_active, sort_order, created_at, updated_at
            ) VALUES (
                1, 'old-file', 'photo', 'uz', 'ru', 'en', 1, 10,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            INSERT INTO broadcasts (
                id, request_token, admin_telegram_id, admin_language, media_type,
                telegram_file_id, text_uz, text_ru, text_en, status,
                cancellation_requested, created_at
            ) VALUES (
                5, 'kept-token', 10, 'en', 'text', '', 'uz', 'ru', 'en',
                'completed', 0, CURRENT_TIMESTAMP
            );
            """
        )

    database = create_database(database_path)
    await database.initialize()
    await database.close()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT telegram_id FROM users").fetchone()[0] == 42
        assert connection.execute("SELECT request_token FROM broadcasts").fetchone()[0] == (
            "kept-token"
        )
        assert not connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='media'"
        ).fetchone()
        assert connection.execute(
            "SELECT name_uz, name_ru, name_en, is_active FROM content_options"
        ).fetchone() == (
            "Import qilingan kontent",
            "Импортированный контент",
            "Imported content",
            0,
        )
        assert connection.execute(
            "SELECT telegram_file_id, media_type, text_uz, text_ru, text_en, sort_order "
            "FROM option_content_items"
        ).fetchone() == ("old-file", "photo", "uz", "ru", "en", 10)
    check_database(database_path)


async def test_version_two_import_fills_blank_legacy_text_without_enabling_it(
    tmp_path,
) -> None:
    database_path = tmp_path / "version-two-blank-content.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA user_version=2;
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, telegram_id BIGINT NOT NULL UNIQUE,
                phone_number VARCHAR(32), username VARCHAR(64), first_name VARCHAR(255),
                last_name VARCHAR(255), language_code VARCHAR(2), phone_verified_at DATETIME,
                subscription_verified_at DATETIME, subscription_prompt_message_id BIGINT,
                is_reachable BOOLEAN NOT NULL, unreachable_at DATETIME,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            );
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY, telegram_chat_id VARCHAR(64) NOT NULL UNIQUE,
                title VARCHAR(255) NOT NULL, join_url VARCHAR(512) NOT NULL,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            );
            CREATE TABLE media (
                id INTEGER PRIMARY KEY, telegram_file_id VARCHAR(512) NOT NULL,
                telegram_file_unique_id VARCHAR(255), media_type VARCHAR(20) NOT NULL,
                original_filename VARCHAR(255), caption TEXT, text_uz TEXT, text_ru TEXT,
                text_en TEXT, is_active BOOLEAN NOT NULL, sort_order INTEGER NOT NULL,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            );
            CREATE TABLE broadcasts (
                id INTEGER PRIMARY KEY, request_token VARCHAR(64) NOT NULL UNIQUE,
                admin_telegram_id BIGINT NOT NULL, admin_language VARCHAR(2) NOT NULL,
                media_type VARCHAR(20) NOT NULL, telegram_file_id VARCHAR(512) NOT NULL,
                telegram_file_unique_id VARCHAR(255), original_filename VARCHAR(255),
                text_uz TEXT NOT NULL, text_ru TEXT NOT NULL, text_en TEXT NOT NULL,
                status VARCHAR(20) NOT NULL, cancellation_requested BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL, started_at DATETIME, finished_at DATETIME
            );
            CREATE TABLE broadcast_recipients (
                id INTEGER PRIMARY KEY, broadcast_id INTEGER NOT NULL,
                telegram_id BIGINT NOT NULL, language_code VARCHAR(2) NOT NULL,
                status VARCHAR(20) NOT NULL, attempt_count INTEGER NOT NULL,
                next_attempt_at DATETIME, last_error TEXT, sent_at DATETIME,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            );
            INSERT INTO media (
                id, telegram_file_id, media_type, caption, text_uz, text_ru, text_en,
                is_active, sort_order, created_at, updated_at
            ) VALUES (
                1, 'file', 'video', NULL, '', NULL, '', 1, 20,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            """
        )

    database = create_database(database_path)
    await database.initialize()
    await database.close()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT is_active FROM content_options").fetchone() == (0,)
        texts = connection.execute(
            "SELECT text_uz, text_ru, text_en FROM option_content_items"
        ).fetchone()
        assert texts == (
            "Import qilingan kontent",
            "Импортированный контент",
            "Imported content",
        )


async def test_incomplete_current_schema_is_rejected(tmp_path) -> None:
    database_path = tmp_path / "incomplete.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            f"""
            PRAGMA user_version={SCHEMA_VERSION};
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            """
        )

    database = create_database(database_path)
    with pytest.raises(SchemaMigrationError, match="missing"):
        await database.initialize()
    await database.close()
