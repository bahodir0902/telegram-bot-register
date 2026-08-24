from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.config import Settings
from app.db.session import Database, create_database

TEST_TOKEN = "123456789:abcdefghijklmnopqrstuvwxyzABCDE"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        BOT_TOKEN=TEST_TOKEN,
        CHANNEL_ID="@example_channel",
        CHANNEL_URL="https://t.me/example_channel",
        ADMIN_IDS="10,20",
        DATABASE_PATH=tmp_path / "bot.sqlite3",
        MEDIA_ROOT=tmp_path / "media",
    )


@pytest_asyncio.fixture
async def database(tmp_path) -> AsyncIterator[Database]:
    database = create_database(tmp_path / "test.sqlite3")
    await database.initialize()
    try:
        yield database
    finally:
        await database.close()
