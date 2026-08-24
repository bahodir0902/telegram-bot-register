import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.conftest import TEST_TOKEN


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "BOT_TOKEN": TEST_TOKEN,
        "CHANNEL_ID": "-1001234567890",
        "CHANNEL_URL": "https://t.me/example_channel",
        "ADMIN_IDS": "123,456,123",
        "DATABASE_PATH": "./data/test.sqlite3",
        "MEDIA_ROOT": "./media",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_configuration_parses_ids_and_paths() -> None:
    settings = make_settings()

    assert settings.channel_id == -1001234567890
    assert settings.admin_ids == frozenset({123, 456})
    assert str(settings.database_path) == "data/test.sqlite3"
    assert TEST_TOKEN not in repr(settings)


def test_admin_ids_parse_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("CHANNEL_ID", "@example_channel")
    monkeypatch.setenv("CHANNEL_URL", "https://t.me/example_channel")
    monkeypatch.setenv("ADMIN_IDS", "123,456")

    settings = Settings(_env_file=None)

    assert settings.admin_ids == frozenset({123, 456})


@pytest.mark.parametrize("admin_ids", ["", "1,", "abc", "0", "-1,2"])
def test_configuration_rejects_malformed_admin_ids(admin_ids: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(ADMIN_IDS=admin_ids)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("BOT_TOKEN", "not-a-token"),
        ("CHANNEL_ID", "channel without at"),
        ("CHANNEL_URL", "https://example.com/channel"),
    ],
)
def test_configuration_rejects_invalid_required_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})
