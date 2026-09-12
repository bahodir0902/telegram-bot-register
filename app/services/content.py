from __future__ import annotations

from collections.abc import Awaitable, Callable
from html import escape
from typing import Protocol

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from app.db.models import MediaType
from app.i18n import DEFAULT_LANGUAGE, Language

TEXT_LIMIT = 10_000
CAPTION_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_MESSAGE_LIMIT = 4096


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
    protect_content: bool = False,
) -> None:
    markup: dict[str, object] = {}
    if protect_content:
        markup["protect_content"] = True
    if reply_markup is not None:
        markup["reply_markup"] = reply_markup
    if media_type == MediaType.TEXT:
        await _send_text_chunks(bot, chat_id, text, markup=markup)
    elif media_type == MediaType.VIDEO:
        await _send_media_with_content(
            bot.send_video, bot, chat_id, telegram_file_id, text, markup=markup
        )
    elif media_type == MediaType.PHOTO:
        await _send_media_with_content(
            bot.send_photo, bot, chat_id, telegram_file_id, text, markup=markup
        )
    else:
        await _send_media_with_content(
            bot.send_document, bot, chat_id, telegram_file_id, text, markup=markup
        )


async def _send_text_chunks(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    markup: dict[str, object],
) -> None:
    chunks = [
        text[offset : offset + TELEGRAM_MESSAGE_LIMIT]
        for offset in range(0, len(text), TELEGRAM_MESSAGE_LIMIT)
    ]
    for index, chunk in enumerate(chunks):
        await bot.send_message(
            chat_id,
            escape(chunk),
            **(markup if index == len(chunks) - 1 else {}),
        )


async def _send_media_with_content(
    send_media: Callable[..., Awaitable[object]],
    bot: Bot,
    chat_id: int,
    telegram_file_id: str,
    text: str,
    *,
    markup: dict[str, object],
) -> None:
    caption = text[:TELEGRAM_CAPTION_LIMIT]
    remaining_text = text[TELEGRAM_CAPTION_LIMIT:]
    await send_media(
        chat_id,
        telegram_file_id,
        caption=escape(caption),
        **(markup if not remaining_text else {}),
    )
    if remaining_text:
        await _send_text_chunks(bot, chat_id, remaining_text, markup=markup)
