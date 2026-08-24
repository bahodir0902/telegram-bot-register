from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Media, MediaType
from app.db.session import AsyncSessionFactory

logger = logging.getLogger(__name__)


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
) -> Media:
    highest_order = await session.scalar(select(func.max(Media.sort_order)))
    item = Media(
        telegram_file_id=telegram_file_id,
        telegram_file_unique_id=telegram_file_unique_id,
        media_type=media_type,
        original_filename=original_filename,
        caption=caption,
        is_active=True,
        sort_order=(highest_order or 0) + 10,
    )
    session.add(item)
    await session.flush()
    return item


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
) -> DeliveryReport:
    async with session_factory() as session:
        items = await get_active_media(session)

    sent = 0
    failed = 0
    for item in items:
        try:
            if item.media_type == MediaType.VIDEO:
                await bot.send_video(
                    user_id,
                    item.telegram_file_id,
                    caption=escape(item.caption) if item.caption else None,
                )
            elif item.media_type == MediaType.PHOTO:
                await bot.send_photo(
                    user_id,
                    item.telegram_file_id,
                    caption=escape(item.caption) if item.caption else None,
                )
            else:
                await bot.send_document(
                    user_id,
                    item.telegram_file_id,
                    caption=escape(item.caption) if item.caption else None,
                )
            sent += 1
        except TelegramAPIError:
            failed += 1
            logger.exception(
                "Failed to deliver media",
                extra={"media_id": item.id, "user_id": user_id},
            )
    return DeliveryReport(total=len(items), sent=sent, failed=failed)
