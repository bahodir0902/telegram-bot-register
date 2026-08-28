from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContentOption, MediaType, OptionContentItem
from app.i18n import DEFAULT_LANGUAGE, Language
from app.services.content import localized_content_text, send_content, validate_content_text

logger = logging.getLogger(__name__)
OPTION_NAME_LIMIT = 64


class EmptyOptionError(ValueError):
    """An empty option cannot be exposed to users."""


@dataclass(frozen=True, slots=True)
class OptionItemInput:
    media_type: MediaType
    telegram_file_id: str
    telegram_file_unique_id: str | None
    original_filename: str | None
    text_uz: str
    text_ru: str
    text_en: str


@dataclass(frozen=True, slots=True)
class OptionPage:
    items: tuple[ContentOption, ...]
    page: int
    pages: int
    total: int


@dataclass(frozen=True, slots=True)
class OptionItemPage:
    items: tuple[OptionContentItem, ...]
    page: int
    pages: int
    total: int


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    total: int
    sent: int
    failed: int


def validate_option_name(value: str | None) -> str:
    if value is None or not value.strip():
        raise ValueError("option name cannot be empty")
    normalized = value.strip()
    if len(normalized) > OPTION_NAME_LIMIT:
        raise ValueError(f"option name exceeds {OPTION_NAME_LIMIT} characters")
    return normalized


def localized_option_name(option: ContentOption, language: Language | str | None) -> str:
    try:
        resolved = Language(language) if language is not None else DEFAULT_LANGUAGE
    except ValueError:
        resolved = DEFAULT_LANGUAGE
    return {
        Language.UZ: option.name_uz,
        Language.RU: option.name_ru,
        Language.EN: option.name_en,
    }[resolved]


def validate_item_input(item: OptionItemInput) -> OptionItemInput:
    validate_content_text(item.text_uz, item.media_type)
    validate_content_text(item.text_ru, item.media_type)
    validate_content_text(item.text_en, item.media_type)
    if item.media_type != MediaType.TEXT and not item.telegram_file_id:
        raise ValueError("media content requires a Telegram file ID")
    return item


async def create_option(
    session: AsyncSession,
    *,
    name_uz: str,
    name_ru: str,
    name_en: str,
    items: tuple[OptionItemInput, ...],
) -> ContentOption:
    if not items:
        raise EmptyOptionError("an option requires at least one content item")
    highest_order = await session.scalar(select(func.max(ContentOption.sort_order)))
    option = ContentOption(
        name_uz=validate_option_name(name_uz),
        name_ru=validate_option_name(name_ru),
        name_en=validate_option_name(name_en),
        is_active=True,
        sort_order=(highest_order or 0) + 10,
    )
    session.add(option)
    await session.flush()
    for item in items:
        await add_option_item(session, option.id, item)
    return option


async def get_option(session: AsyncSession, option_id: int) -> ContentOption | None:
    return await session.get(ContentOption, option_id)


async def get_option_item(session: AsyncSession, item_id: int) -> OptionContentItem | None:
    return await session.get(OptionContentItem, item_id)


async def get_option_items(session: AsyncSession, option_id: int) -> tuple[OptionContentItem, ...]:
    result = await session.scalars(
        select(OptionContentItem)
        .where(OptionContentItem.option_id == option_id)
        .order_by(OptionContentItem.sort_order.asc(), OptionContentItem.id.asc())
    )
    return tuple(result.all())


async def list_options(
    session: AsyncSession, *, page: int, page_size: int = 5, active_only: bool = False
) -> OptionPage:
    count_query = select(func.count(ContentOption.id))
    query = select(ContentOption)
    if active_only:
        item_exists = (
            select(OptionContentItem.id)
            .where(OptionContentItem.option_id == ContentOption.id)
            .exists()
        )
        count_query = count_query.where(ContentOption.is_active.is_(True), item_exists)
        query = query.where(ContentOption.is_active.is_(True), item_exists)
    total = int(await session.scalar(count_query) or 0)
    pages = max(1, math.ceil(total / page_size))
    normalized_page = min(max(page, 0), pages - 1)
    result = await session.scalars(
        query.order_by(ContentOption.sort_order.asc(), ContentOption.id.asc())
        .offset(normalized_page * page_size)
        .limit(page_size)
    )
    return OptionPage(tuple(result.all()), normalized_page, pages, total)


async def list_option_items(
    session: AsyncSession, *, option_id: int, page: int, page_size: int = 5
) -> OptionItemPage:
    total = int(
        await session.scalar(
            select(func.count(OptionContentItem.id)).where(OptionContentItem.option_id == option_id)
        )
        or 0
    )
    pages = max(1, math.ceil(total / page_size))
    normalized_page = min(max(page, 0), pages - 1)
    result = await session.scalars(
        select(OptionContentItem)
        .where(OptionContentItem.option_id == option_id)
        .order_by(OptionContentItem.sort_order.asc(), OptionContentItem.id.asc())
        .offset(normalized_page * page_size)
        .limit(page_size)
    )
    return OptionItemPage(tuple(result.all()), normalized_page, pages, total)


async def update_option_name(
    session: AsyncSession, option_id: int, language: Language, value: str
) -> ContentOption | None:
    option = await get_option(session, option_id)
    if option is None:
        return None
    setattr(option, f"name_{language.value}", validate_option_name(value))
    return option


async def set_option_active(session: AsyncSession, option_id: int, active: bool) -> bool:
    if await get_option(session, option_id) is None:
        return False
    if active:
        item_count = int(
            await session.scalar(
                select(func.count(OptionContentItem.id)).where(
                    OptionContentItem.option_id == option_id
                )
            )
            or 0
        )
        if not item_count:
            raise EmptyOptionError("an empty option cannot be activated")
    result = await session.execute(
        update(ContentOption).where(ContentOption.id == option_id).values(is_active=active)
    )
    return result.rowcount == 1


async def delete_option(session: AsyncSession, option_id: int) -> bool:
    result = await session.execute(delete(ContentOption).where(ContentOption.id == option_id))
    return result.rowcount == 1


async def add_option_item(
    session: AsyncSession, option_id: int, item_input: OptionItemInput
) -> OptionContentItem | None:
    if await get_option(session, option_id) is None:
        return None
    item_input = validate_item_input(item_input)
    highest_order = await session.scalar(
        select(func.max(OptionContentItem.sort_order)).where(
            OptionContentItem.option_id == option_id
        )
    )
    item = OptionContentItem(
        option_id=option_id,
        media_type=item_input.media_type,
        telegram_file_id=item_input.telegram_file_id,
        telegram_file_unique_id=item_input.telegram_file_unique_id,
        original_filename=item_input.original_filename,
        text_uz=item_input.text_uz,
        text_ru=item_input.text_ru,
        text_en=item_input.text_en,
        sort_order=(highest_order or 0) + 10,
    )
    session.add(item)
    await session.flush()
    return item


async def replace_option_item(
    session: AsyncSession, item_id: int, item_input: OptionItemInput
) -> OptionContentItem | None:
    item = await get_option_item(session, item_id)
    if item is None:
        return None
    item_input = validate_item_input(item_input)
    item.media_type = item_input.media_type
    item.telegram_file_id = item_input.telegram_file_id
    item.telegram_file_unique_id = item_input.telegram_file_unique_id
    item.original_filename = item_input.original_filename
    item.text_uz = item_input.text_uz
    item.text_ru = item_input.text_ru
    item.text_en = item_input.text_en
    return item


async def update_option_item_text(
    session: AsyncSession, item_id: int, language: Language, value: str
) -> OptionContentItem | None:
    item = await get_option_item(session, item_id)
    if item is None:
        return None
    setattr(item, f"text_{language.value}", validate_content_text(value, item.media_type))
    return item


async def delete_option_item(session: AsyncSession, item_id: int) -> tuple[bool, int | None]:
    item = await get_option_item(session, item_id)
    if item is None:
        return False, None
    option_id = item.option_id
    await session.delete(item)
    await session.flush()
    remaining = int(
        await session.scalar(
            select(func.count(OptionContentItem.id)).where(OptionContentItem.option_id == option_id)
        )
        or 0
    )
    if not remaining:
        await session.execute(
            update(ContentOption).where(ContentOption.id == option_id).values(is_active=False)
        )
    return True, option_id


async def _move_ordered(
    session: AsyncSession,
    *,
    model: type[ContentOption] | type[OptionContentItem],
    object_id: int,
    direction: int,
    option_id: int | None = None,
) -> bool:
    if direction not in {-1, 1}:
        return False
    query = select(model)
    if option_id is not None:
        query = query.where(OptionContentItem.option_id == option_id)
    ordered = list(
        (await session.scalars(query.order_by(model.sort_order.asc(), model.id.asc()))).all()
    )
    try:
        current_index = next(
            index for index, current in enumerate(ordered) if current.id == object_id
        )
    except StopIteration:
        return False
    target_index = current_index + direction
    if target_index < 0 or target_index >= len(ordered):
        return False
    ordered[current_index], ordered[target_index] = (
        ordered[target_index],
        ordered[current_index],
    )
    for index, current in enumerate(ordered, start=1):
        current.sort_order = index * 10
    await session.flush()
    return True


async def move_option(session: AsyncSession, option_id: int, direction: int) -> bool:
    return await _move_ordered(
        session, model=ContentOption, object_id=option_id, direction=direction
    )


async def move_option_item(session: AsyncSession, item_id: int, direction: int) -> bool:
    item = await get_option_item(session, item_id)
    if item is None:
        return False
    return await _move_ordered(
        session,
        model=OptionContentItem,
        object_id=item_id,
        direction=direction,
        option_id=item.option_id,
    )


async def deliver_option_items(
    bot: Bot,
    user_id: int,
    items: tuple[OptionContentItem, ...],
    language: Language,
) -> DeliveryReport:
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
                "Failed to deliver option content",
                extra={"option_id": item.option_id, "item_id": item.id, "user_id": user_id},
            )
    return DeliveryReport(total=len(items), sent=sent, failed=failed)
