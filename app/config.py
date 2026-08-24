from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.validation import parse_channel_id, validate_channel_url

BOT_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")


class Settings(BaseSettings):
    """Validated deployment configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: SecretStr = Field(validation_alias="BOT_TOKEN")
    channel_id: int | str = Field(validation_alias="CHANNEL_ID")
    channel_url: str = Field(validation_alias="CHANNEL_URL")
    admin_ids: Annotated[frozenset[int], NoDecode] = Field(validation_alias="ADMIN_IDS")
    database_path: Path = Field(
        default=Path("./data/bot.sqlite3"), validation_alias="DATABASE_PATH"
    )
    media_root: Path = Field(default=Path("./media"), validation_alias="MEDIA_ROOT")

    @field_validator("bot_token", mode="before")
    @classmethod
    def validate_bot_token(cls, value: object) -> object:
        if not isinstance(value, str) or not BOT_TOKEN_RE.fullmatch(value.strip()):
            raise ValueError("BOT_TOKEN must have the format '<numeric-id>:<token>'")
        return value.strip()

    @field_validator("channel_id", mode="before")
    @classmethod
    def parse_channel_id(cls, value: object) -> int | str:
        try:
            return parse_channel_id(value)
        except ValueError as exc:
            raise ValueError(f"CHANNEL_ID {exc}") from exc

    @field_validator("channel_url")
    @classmethod
    def validate_channel_url(cls, value: str) -> str:
        try:
            return validate_channel_url(value)
        except ValueError as exc:
            raise ValueError(f"CHANNEL_URL {exc}") from exc

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> frozenset[int]:
        raw_values: list[object]
        if isinstance(value, str):
            raw_values = [part.strip() for part in value.split(",")]
            if not all(raw_values):
                raise ValueError("ADMIN_IDS must be a comma-separated list of positive IDs")
        elif isinstance(value, (list, tuple, set, frozenset)):
            raw_values = list(value)
        else:
            raise ValueError("ADMIN_IDS must be a comma-separated list of positive IDs")

        try:
            parsed = frozenset(int(item) for item in raw_values)
        except (TypeError, ValueError) as exc:
            raise ValueError("ADMIN_IDS must contain integers only") from exc
        if not parsed or any(admin_id <= 0 for admin_id in parsed):
            raise ValueError("ADMIN_IDS must contain at least one positive Telegram user ID")
        return parsed

    @field_validator("database_path", "media_root", mode="before")
    @classmethod
    def normalize_path(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ValueError("Filesystem paths cannot be empty")
        return Path(value).expanduser()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
