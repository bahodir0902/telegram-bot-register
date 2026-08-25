from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from html import escape
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Media, MediaType
from app.db.session import AsyncSessionFactory
from app.i18n import DEFAULT_LANGUAGE, Language

logger = logging.getLogger(__name__)

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024


class LocalizedContent(Protocol):
    media_type: MediaType
    telegram_file_id: str
    text_uz: str | None
    text_ru: str | None
    text_en: str | None


class ContentValidationError(ValueError):
    """Admin-authored content is empty or outside Telegram's limits."""


@dataclass(frozen=True, slots=True)
class MediaPage:
    items: tuple[Media, ...]
    page: int
    pages: int
    total: int


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    total: int
    sent: int
    failed: int


async def add_media(
    session: AsyncSession,
    *,
    telegram_file_id: str,
    telegram_file_unique_id: str | None,
    media_type: MediaType,
    original_filename: str | None,
    caption: str | None,
    text_uz: str | None = None,
    text_ru: str | None = None,
    text_en: str | None = None,
) -> Media:
    localized_uz = text_uz if text_uz is not None else caption
    localized_ru = text_ru if text_ru is not None else caption
    localized_en = text_en if text_en is not None else caption
    highest_order = await session.scalar(select(func.max(Media.sort_order)))
    item = Media(
        telegram_file_id=telegram_file_id,
        telegram_file_unique_id=telegram_file_unique_id,
        media_type=media_type,
        original_filename=original_filename,
        caption=localized_uz,
        text_uz=localized_uz,
        text_ru=localized_ru,
        text_en=localized_en,
        is_active=True,
        sort_order=(highest_order or 0) + 10,
    )
    session.add(item)
    await session.flush()
    return item


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
    return selected or item.text_uz or item.text_ru or item.text_en or ""


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
        await bot.send_video(
            chat_id,
            telegram_file_id,
            caption=rendered or None,
            **markup,
        )
    elif media_type == MediaType.PHOTO:
        await bot.send_photo(
            chat_id,
            telegram_file_id,
            caption=rendered or None,
            **markup,
        )
    else:
        await bot.send_document(
            chat_id,
            telegram_file_id,
            caption=rendered or None,
            **markup,
        )


async def get_media(session: AsyncSession, media_id: int) -> Media | None:
    return await session.get(Media, media_id)


async def get_active_media(session: AsyncSession) -> tuple[Media, ...]:
    result = await session.scalars(
        select(Media)
        .where(Media.is_active.is_(True))
        .order_by(Media.sort_order.asc(), Media.id.asc())
    )
    return tuple(result.all())


async def list_media(session: AsyncSession, *, page: int, page_size: int = 5) -> MediaPage:
    total = int(await session.scalar(select(func.count(Media.id))) or 0)
    pages = max(1, math.ceil(total / page_size))
    normalized_page = min(max(page, 0), pages - 1)
    result = await session.scalars(
        select(Media)
        .order_by(Media.sort_order.asc(), Media.id.asc())
        .offset(normalized_page * page_size)
        .limit(page_size)
    )
    return MediaPage(tuple(result.all()), normalized_page, pages, total)


async def set_media_active(session: AsyncSession, media_id: int, active: bool) -> bool:
    result = await session.execute(
        update(Media).where(Media.id == media_id).values(is_active=active)
    )
    return result.rowcount == 1


async def delete_media(session: AsyncSession, media_id: int) -> bool:
    result = await session.execute(delete(Media).where(Media.id == media_id))
    return result.rowcount == 1


async def deliver_active_media(
    bot: Bot,
    user_id: int,
    session_factory: AsyncSessionFactory,
    language: Language = DEFAULT_LANGUAGE,
) -> DeliveryReport:
    async with session_factory() as session:
        items = await get_active_media(session)

    sent = 0
    failed = 0
    for item in items:
        try:
            await send_content(
                bot,
                user_id,
                media_type=item.media_type,
                telegram_file_id=item.telegram_file_id,
                text=localized_content_text(item, language),
            )
            sent += 1
        except TelegramAPIError:
            failed += 1
            logger.exception(
                "Failed to deliver content",
                extra={"media_id": item.id, "user_id": user_id},
            )
    return DeliveryReport(total=len(items), sent=sent, failed=failed)
