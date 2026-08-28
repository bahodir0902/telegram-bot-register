from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import LanguageCallback
from app.bot.handlers.start import continue_onboarding, send_language_selector
from app.bot.keyboards.user import language_keyboard
from app.bot.messages import answer_callback_safely
from app.db.session import AsyncSessionFactory
from app.i18n import LANGUAGE_BUTTON_TEXT, Language, tr
from app.services.users import set_user_language, upsert_user

router = Router(name="language")


@router.message(Command("language"), F.chat.type == ChatType.PRIVATE)
@router.message(F.text == LANGUAGE_BUTTON_TEXT, F.chat.type == ChatType.PRIVATE)
async def choose_language(
    message: Message,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    sender = message.from_user
    if sender is None:
        return
    async with session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=sender.id,
            username=sender.username,
            first_name=sender.first_name,
            last_name=sender.last_name,
        )
    await send_language_selector(message, language)


@router.callback_query(LanguageCallback.filter())
async def set_language(
    callback: CallbackQuery,
    callback_data: LanguageCallback,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        selected = Language(callback_data.code)
    except ValueError:
        await answer_callback_safely(
            callback,
            tr(Language.UZ, "language_invalid"),
            show_alert=True,
        )
        return

    sender = callback.from_user
    message = callback.message
    if sender is None or not isinstance(message, Message):
        await answer_callback_safely(callback)
        return

    async with session_factory.begin() as session:
        user = await upsert_user(
            session,
            telegram_id=sender.id,
            username=sender.username,
            first_name=sender.first_name,
            last_name=sender.last_name,
        )
        first_selection = user.language_code is None
        await set_user_language(session, sender.id, selected)

    await answer_callback_safely(callback, tr(selected, "language_changed"))
    if first_selection:
        await continue_onboarding(message, sender, selected, session_factory)
        return
    await message.answer(
        tr(selected, "language_changed"),
        reply_markup=language_keyboard(selected),
    )


@router.callback_query(F.data.startswith("language:"))
async def reject_language_callback(callback: CallbackQuery, language: Language) -> None:
    await answer_callback_safely(
        callback,
        tr(language, "language_invalid"),
        show_alert=True,
    )
