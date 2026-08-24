from __future__ import annotations

import re
from urllib.parse import urlparse

CHANNEL_USERNAME_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{4,31}$")


def parse_channel_id(value: object) -> int | str:
    if isinstance(value, int):
        if value == 0:
            raise ValueError("channel ID cannot be zero")
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("channel ID must be a Telegram numeric ID or @username")
    cleaned = value.strip()
    if cleaned.lstrip("-").isdigit():
        parsed = int(cleaned)
        if parsed == 0:
            raise ValueError("channel ID cannot be zero")
        return parsed
    if not CHANNEL_USERNAME_RE.fullmatch(cleaned):
        raise ValueError("channel ID must be numeric or a valid @channel_username")
    return cleaned


def canonical_channel_id(value: object) -> str:
    parsed = parse_channel_id(value)
    return parsed.lower() if isinstance(parsed, str) else str(parsed)


def validate_channel_url(value: str) -> str:
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or parsed.hostname not in {"t.me", "telegram.me"}:
        raise ValueError("channel URL must be an https://t.me/... Telegram link")
    if not parsed.path or parsed.path == "/":
        raise ValueError("channel URL must identify a Telegram channel")
    return cleaned
