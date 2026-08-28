from __future__ import annotations

from html import escape
from typing import Protocol

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from app.db.models import MediaType
from app.i18n import DEFAULT_LANGUAGE, Language

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024


class LocalizedContent(Protocol):
    media_type: MediaType
    telegram_file_id: str
    text_uz: str | None
    text_ru: str | None
    text_en: str | None


class ContentValidationError(ValueError):
    """Administrator-authored content is empty or outside Telegram's limits."""


def validate_content_text(value: str | None, media_type: MediaType) -> str:
    if value is None or not value.strip():
        raise ContentValidationError("content cannot be empty")
    limit = TEXT_LIMIT if media_type == MediaType.TEXT else CAPTION_LIMIT
    if len(value) > limit:
        raise ContentValidationError(f"content exceeds Telegram's {limit}-character limit")
    return value


def localized_content_text(
    item: LocalizedContent,
    language: Language | str | None,
) -> str:
    try:
        resolved = Language(language) if language is not None else DEFAULT_LANGUAGE
    except ValueError:
        resolved = DEFAULT_LANGUAGE
    selected = {
        Language.UZ: item.text_uz,
        Language.RU: item.text_ru,
        Language.EN: item.text_en,
    }[resolved]
    return selected or ""


async def send_content(
    bot: Bot,
    chat_id: int,
    *,
    media_type: MediaType,
    telegram_file_id: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    rendered = escape(text)
    markup = {"reply_markup": reply_markup} if reply_markup is not None else {}
    if media_type == MediaType.TEXT:
        await bot.send_message(chat_id, rendered, **markup)
    elif media_type == MediaType.VIDEO:
        await bot.send_video(chat_id, telegram_file_id, caption=rendered, **markup)
    elif media_type == MediaType.PHOTO:
        await bot.send_photo(chat_id, telegram_file_id, caption=rendered, **markup)
    else:
        await bot.send_document(chat_id, telegram_file_id, caption=rendered, **markup)
