from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.types import User as TelegramUser

from app.bot.keyboards.user import (
    contact_keyboard,
    language_keyboard,
    language_selector_keyboard,
    subscription_keyboard,
)
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr
from app.services.channels import get_channels
from app.services.users import get_user, set_subscription_prompt, upsert_user

router = Router(name="start")


async def send_language_selector(message: Message, language: Language) -> Message:
    return await message.answer(
        tr(language, "language_prompt"),
        reply_markup=language_selector_keyboard(),
    )


async def send_subscription_prompt(
    message: Message,
    telegram_user: TelegramUser,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> Message | None:
    async with session_factory() as session:
        channels = await get_channels(session)
    if not channels:
        await message.answer(tr(language, "subscription_no_channels"))
        return None
    prompt = await message.answer(
        tr(language, "subscription_prompt"),
        reply_markup=subscription_keyboard(channels, language),
    )
    async with session_factory.begin() as session:
        await set_subscription_prompt(session, telegram_user.id, prompt.message_id)
    return prompt


async def continue_onboarding(
    message: Message,
    telegram_user: TelegramUser,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        user = await get_user(session, telegram_user.id)
    if user is None:
        return

    await message.answer(
        tr(language, "welcome"),
        reply_markup=language_keyboard(language) if user.phone_verified_at is not None else None,
    )
    if user.phone_verified_at is None:
        await message.answer(
            tr(language, "contact_prompt"),
            reply_markup=contact_keyboard(language),
        )
        return
    await send_subscription_prompt(message, telegram_user, language, session_factory)


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def start_private(
    message: Message,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    sender = message.from_user
    if sender is None:
        return

    async with session_factory.begin() as session:
        user = await upsert_user(
            session,
            telegram_id=sender.id,
            username=sender.username,
            first_name=sender.first_name,
            last_name=sender.last_name,
        )

    if user.language_code is None:
        await send_language_selector(message, language)
        return
    await continue_onboarding(message, sender, user.language_code, session_factory)


@router.message(CommandStart())
async def start_outside_private(message: Message, language: Language) -> None:
    await message.answer(tr(language, "outside_private"))
