from __future__ import annotations

import logging
import sqlite3

import pytest

from app.config import Settings
from app.db.base import Base
from app.db.session import create_database
from app.health import HealthcheckError, check_database
from app.main import healthcheck_or_exit
from tests.conftest import TEST_TOKEN


def test_database_session_registers_expected_tables() -> None:
    assert {"media", "users"}.issubset(Base.metadata.tables)


@pytest.mark.asyncio
async def test_healthcheck_accepts_initialized_database(tmp_path) -> None:
    database_path = tmp_path / "healthy.sqlite3"
    database = create_database(database_path)
    await database.initialize()
    await database.close()

    check_database(database_path)


def test_healthcheck_does_not_create_missing_database(tmp_path) -> None:
    database_path = tmp_path / "missing.sqlite3"

    with pytest.raises(HealthcheckError, match="does not exist"):
        check_database(database_path)

    assert not database_path.exists()


def test_healthcheck_rejects_uninitialized_schema(tmp_path) -> None:
    database_path = tmp_path / "empty.sqlite3"
    with sqlite3.connect(database_path):
        pass

    with pytest.raises(HealthcheckError, match="missing tables: media, users"):
        check_database(database_path)


def test_healthcheck_rejects_corrupt_database(tmp_path) -> None:
    database_path = tmp_path / "corrupt.sqlite3"
    database_path.write_bytes(b"this is not sqlite")

    with pytest.raises(HealthcheckError, match="cannot be opened or queried"):
        check_database(database_path)


def test_healthcheck_failure_does_not_log_bot_token(tmp_path, caplog) -> None:
    settings = Settings(
        _env_file=None,
        BOT_TOKEN=TEST_TOKEN,
        CHANNEL_ID="@example_channel",
        CHANNEL_URL="https://t.me/example_channel",
        ADMIN_IDS="10",
        DATABASE_PATH=tmp_path / "missing.sqlite3",
        MEDIA_ROOT=tmp_path / "media",
    )

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc_info:
        healthcheck_or_exit(settings)

    assert exc_info.value.code == 1
    assert TEST_TOKEN not in caplog.text
