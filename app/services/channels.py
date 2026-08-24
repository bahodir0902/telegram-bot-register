from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Channel
from app.db.session import AsyncSessionFactory
from app.validation import canonical_channel_id, parse_channel_id, validate_channel_url


class ChannelValidationKind(StrEnum):
    INVALID_ID = "invalid_id"
    LOOKUP_FAILED = "lookup_failed"
    NOT_CHANNEL = "not_channel"
    BOT_NOT_ADMIN = "bot_not_admin"


class ChannelValidationError(ValueError):
    def __init__(self, kind: ChannelValidationKind) -> None:
        self.kind = kind
        super().__init__(kind.value)


class ChannelAlreadyExistsError(RuntimeError):
    pass


class LastChannelDeletionError(RuntimeError):
    pass


class ChannelBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedChannel:
    telegram_chat_id: str
    title: str


@dataclass(frozen=True, slots=True)
class ChannelPage:
    items: tuple[Channel, ...]
    page: int
    pages: int
    total: int


def channel_chat_id(channel: Channel) -> int | str:
    return parse_channel_id(channel.telegram_chat_id)


async def validate_telegram_channel(bot: Bot, raw_chat_id: object) -> ValidatedChannel:
    try:
        parsed = parse_channel_id(raw_chat_id)
        canonical = canonical_channel_id(parsed)
    except ValueError as exc:
        raise ChannelValidationError(ChannelValidationKind.INVALID_ID) from exc

    try:
        chat = await bot.get_chat(parsed)
        bot_user = await bot.get_me()
        membership = await bot.get_chat_member(parsed, bot_user.id)
    except TelegramAPIError as exc:
        raise ChannelValidationError(ChannelValidationKind.LOOKUP_FAILED) from exc

    if chat.type != ChatType.CHANNEL:
        raise ChannelValidationError(ChannelValidationKind.NOT_CHANNEL)
    if membership.status not in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
    }:
        raise ChannelValidationError(ChannelValidationKind.BOT_NOT_ADMIN)

    return ValidatedChannel(canonical, chat.title or canonical)


async def get_channel(session: AsyncSession, channel_id: int) -> Channel | None:
    return await session.get(Channel, channel_id)


async def get_channel_by_chat_id(session: AsyncSession, chat_id: str) -> Channel | None:
    return await session.scalar(select(Channel).where(Channel.telegram_chat_id == chat_id))


async def get_channels(session: AsyncSession) -> tuple[Channel, ...]:
    result = await session.scalars(select(Channel).order_by(Channel.id.asc()))
    return tuple(result.all())


async def channel_signature(session: AsyncSession) -> tuple[tuple[int, str], ...]:
    rows = await session.execute(
        select(Channel.id, Channel.telegram_chat_id).order_by(Channel.id.asc())
    )
    return tuple((int(row[0]), str(row[1])) for row in rows)


async def list_channels(session: AsyncSession, *, page: int, page_size: int = 5) -> ChannelPage:
    total = int(await session.scalar(select(func.count(Channel.id))) or 0)
    pages = max(1, math.ceil(total / page_size))
    normalized_page = min(max(page, 0), pages - 1)
    result = await session.scalars(
        select(Channel)
        .order_by(Channel.id.asc())
        .offset(normalized_page * page_size)
        .limit(page_size)
    )
    return ChannelPage(tuple(result.all()), normalized_page, pages, total)


async def add_channel(
    session: AsyncSession,
    *,
    telegram_chat_id: str,
    title: str,
    join_url: str,
) -> Channel:
    item = Channel(
        telegram_chat_id=canonical_channel_id(telegram_chat_id),
        title=title.strip(),
        join_url=validate_channel_url(join_url),
    )
    try:
        async with session.begin_nested():
            session.add(item)
            await session.flush()
    except IntegrityError as exc:
        raise ChannelAlreadyExistsError from exc
    return item


async def update_channel_identity(
    session: AsyncSession,
    channel_id: int,
    *,
    telegram_chat_id: str,
    title: str,
) -> Channel | None:
    try:
        async with session.begin_nested():
            await session.execute(
                update(Channel)
                .where(Channel.id == channel_id)
                .values(
                    telegram_chat_id=canonical_channel_id(telegram_chat_id),
                    title=title.strip(),
                    updated_at=datetime.now(UTC),
                )
            )
            await session.flush()
    except IntegrityError as exc:
        raise ChannelAlreadyExistsError from exc
    return await get_channel(session, channel_id)


async def update_channel_url(
    session: AsyncSession, channel_id: int, *, join_url: str
) -> Channel | None:
    result = await session.execute(
        update(Channel)
        .where(Channel.id == channel_id)
        .values(join_url=validate_channel_url(join_url), updated_at=datetime.now(UTC))
    )
    if result.rowcount != 1:
        return None
    return await get_channel(session, channel_id)


async def delete_channel(session: AsyncSession, channel_id: int) -> bool:
    channel_count = select(func.count(Channel.id)).scalar_subquery()
    result = await session.execute(
        delete(Channel).where(Channel.id == channel_id, channel_count > 1)
    )
    if result.rowcount == 1:
        return True
    if await get_channel(session, channel_id) is None:
        return False
    raise LastChannelDeletionError


async def bootstrap_initial_channel(
    bot: Bot,
    settings: Settings,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        if int(await session.scalar(select(func.count(Channel.id))) or 0) > 0:
            return

    try:
        validated = await validate_telegram_channel(bot, settings.channel_id)
        join_url = validate_channel_url(settings.channel_url)
    except ChannelValidationError as exc:
        raise ChannelBootstrapError(
            f"the environment bootstrap channel failed validation: {exc.kind.value}"
        ) from exc
    except ValueError as exc:
        raise ChannelBootstrapError("the environment bootstrap channel URL is invalid") from exc

    async with session_factory.begin() as session:
        if int(await session.scalar(select(func.count(Channel.id))) or 0) > 0:
            return
        try:
            await add_channel(
                session,
                telegram_chat_id=validated.telegram_chat_id,
                title=validated.title,
                join_url=join_url,
            )
        except ChannelAlreadyExistsError as exc:
            raise ChannelBootstrapError("could not store the bootstrap channel") from exc
