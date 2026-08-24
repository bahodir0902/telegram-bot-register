from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus, ChatType

from app.db.models import Channel
from app.db.session import Database
from app.services import channels as channel_service
from app.services.channels import (
    ChannelAlreadyExistsError,
    ChannelValidationError,
    ChannelValidationKind,
    LastChannelDeletionError,
    ValidatedChannel,
    add_channel,
    bootstrap_initial_channel,
    delete_channel,
    get_channels,
    update_channel_identity,
    update_channel_url,
    validate_telegram_channel,
)


async def test_channel_crud_duplicate_and_last_delete_guard(database: Database) -> None:
    async with database.session_factory.begin() as session:
        first = await add_channel(
            session,
            telegram_chat_id="@first_channel",
            title="First",
            join_url="https://t.me/first_channel",
        )
        first_id = first.id

    async with database.session_factory.begin() as session:
        with pytest.raises(ChannelAlreadyExistsError):
            await add_channel(
                session,
                telegram_chat_id="@FIRST_CHANNEL",
                title="Duplicate",
                join_url="https://t.me/duplicate",
            )

    async with database.session_factory.begin() as session:
        with pytest.raises(LastChannelDeletionError):
            await delete_channel(session, first_id)
        second = await add_channel(
            session,
            telegram_chat_id="-1001234567890",
            title="Second",
            join_url="https://t.me/+private-link",
        )
        second_id = second.id

    async with database.session_factory.begin() as session:
        updated = await update_channel_identity(
            session,
            second_id,
            telegram_chat_id="@second_channel",
            title="Second renamed",
        )
        assert updated is not None
        assert updated.title == "Second renamed"
        updated = await update_channel_url(
            session, second_id, join_url="https://t.me/second_channel"
        )
        assert updated is not None
        assert updated.join_url == "https://t.me/second_channel"
        assert await delete_channel(session, first_id)


async def test_bootstrap_seeds_only_an_empty_database(
    monkeypatch, database: Database, settings
) -> None:
    calls: list[object] = []

    async def validated(_bot, raw_chat_id) -> ValidatedChannel:
        calls.append(raw_chat_id)
        return ValidatedChannel("@example_channel", "Environment channel")

    monkeypatch.setattr(channel_service, "validate_telegram_channel", validated)
    await bootstrap_initial_channel(object(), settings, database.session_factory)
    await bootstrap_initial_channel(object(), settings, database.session_factory)

    async with database.session_factory() as session:
        channels = await get_channels(session)
    assert [item.title for item in channels] == ["Environment channel"]
    assert calls == [settings.channel_id]


async def test_telegram_channel_validation_requires_channel_and_admin() -> None:
    bot = AsyncMock()
    bot.get_chat.return_value = SimpleNamespace(type=ChatType.CHANNEL, title="Title")
    bot.get_me.return_value = SimpleNamespace(id=99)
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR)

    result = await validate_telegram_channel(bot, "@example_channel")
    assert result == ValidatedChannel("@example_channel", "Title")

    bot.get_chat.return_value = SimpleNamespace(type=ChatType.GROUP, title="Group")
    with pytest.raises(ChannelValidationError) as exc_info:
        await validate_telegram_channel(bot, "@example_channel")
    assert exc_info.value.kind == ChannelValidationKind.NOT_CHANNEL

    bot.get_chat.return_value = SimpleNamespace(type=ChatType.CHANNEL, title="Title")
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    with pytest.raises(ChannelValidationError) as exc_info:
        await validate_telegram_channel(bot, "@example_channel")
    assert exc_info.value.kind == ChannelValidationKind.BOT_NOT_ADMIN


def make_channel(channel_id: int, chat_id: str, title: str) -> Channel:
    return Channel(
        id=channel_id,
        telegram_chat_id=chat_id,
        title=title,
        join_url=f"https://t.me/{title.lower()}",
    )
