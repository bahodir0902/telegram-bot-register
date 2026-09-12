from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import UserLessonCallback
from app.bot.handlers.subscription import restore_subscription_prompt
from app.bot.keyboards.user import lessons_keyboard
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.db.models import EngagementKind
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr, translated_values
from app.services.channels import channel_signature, get_channels
from app.services.lessons import deliver_lesson, get_lesson, get_lesson_videos, list_lessons
from app.services.statistics import record_engagement
from app.services.subscription import check_subscriptions
from app.services.users import get_user, mark_subscription_verified

logger = logging.getLogger(__name__)
router = Router(name="lessons")


async def render_lesson_menu(
    message: Message,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
    *,
    prompt_key: str = "lessons_prompt",
) -> None:
    async with session_factory() as session:
        result = await list_lessons(session, page=page, active_only=True)
    if not result.items:
        await edit_text_safely(message, tr(language, "lessons_empty"))
        return
    await edit_text_safely(
        message,
        tr(language, prompt_key, page=result.page + 1, pages=result.pages),
        reply_markup=lessons_keyboard(result, language),
    )


async def authorize_lesson_access(
    message: Message,
    bot: Bot,
    user_id: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        user = await get_user(session, user_id)
        channels = await get_channels(session)
        initial_signature = await channel_signature(session)
    if user is None or user.phone_verified_at is None:
        await message.answer(tr(language, "lesson_registration_required"))
        return False
    if not channels:
        await edit_text_safely(message, tr(language, "subscription_no_channels"))
        return False
    result = await check_subscriptions(bot, channels, user_id)
    if result.failed:
        logger.warning(
            "Lesson membership checks failed",
            extra={"user_id": user_id, "channel_ids": [c.telegram_chat_id for c in result.failed]},
        )
        async with session_factory() as session:
            current_channels = await get_channels(session)
        await restore_subscription_prompt(
            message,
            user_id,
            current_channels or channels,
            language,
            session_factory,
            text=tr(language, "subscription_check_error"),
        )
        return False
    if result.missing:
        missing = "\n".join(f"• {escape(item.title)}" for item in result.missing)
        async with session_factory() as session:
            current_channels = await get_channels(session)
        await restore_subscription_prompt(
            message,
            user_id,
            current_channels or channels,
            language,
            session_factory,
            text=tr(language, "subscription_missing", channels=missing),
        )
        return False
    async with session_factory() as session:
        current_signature = await channel_signature(session)
        current_channels = await get_channels(session)
    if current_signature != initial_signature:
        if current_channels:
            await restore_subscription_prompt(
                message,
                user_id,
                current_channels,
                language,
                session_factory,
                text=tr(language, "subscription_channels_changed"),
            )
        else:
            await edit_text_safely(message, tr(language, "subscription_no_channels"))
        return False
    async with session_factory.begin() as session:
        await mark_subscription_verified(session, user_id)
    return True


@router.message(F.text.in_(translated_values("show_lessons")), F.chat.type == ChatType.PRIVATE)
async def show_lesson_list(
    message: Message,
    bot: Bot,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    sender = message.from_user
    if sender is None:
        return
    async with session_factory() as session:
        user = await get_user(session, sender.id)
    if user is None or user.phone_verified_at is None:
        await message.answer(tr(language, "lesson_registration_required"))
        return
    status_message = await message.answer(tr(language, "checking_subscription"))
    if await authorize_lesson_access(status_message, bot, sender.id, language, session_factory):
        await render_lesson_menu(status_message, 0, language, session_factory)


@router.callback_query(UserLessonCallback.filter(F.action == "page"))
async def change_lesson_page(
    callback: CallbackQuery,
    callback_data: UserLessonCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    sender = callback.from_user
    message = callback.message
    if sender is None or not isinstance(message, Message):
        return
    async with session_factory() as session:
        user = await get_user(session, sender.id)
    if user is None or user.phone_verified_at is None:
        return
    await render_lesson_menu(message, callback_data.page, language, session_factory)


@router.callback_query(UserLessonCallback.filter(F.action == "select"))
async def select_lesson(
    callback: CallbackQuery,
    callback_data: UserLessonCallback,
    bot: Bot,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback, tr(language, "checking_subscription"))
    sender = callback.from_user
    message = callback.message
    if sender is None or not isinstance(message, Message):
        return
    if message.chat.type != ChatType.PRIVATE or message.chat.id != sender.id:
        return
    if not await authorize_lesson_access(message, bot, sender.id, language, session_factory):
        return
    async with session_factory() as session:
        lesson = await get_lesson(session, callback_data.lesson_id)
        videos = (
            await get_lesson_videos(session, callback_data.lesson_id)
            if lesson is not None and lesson.is_active
            else ()
        )
    if lesson is None or not lesson.is_active or not videos:
        await render_lesson_menu(message, callback_data.page, language, session_factory)
        return
    report = await deliver_lesson(bot, sender.id, lesson, videos, language)
    if report.sent:
        async with session_factory.begin() as session:
            await record_engagement(
                session,
                telegram_id=sender.id,
                kind=EngagementKind.LESSON,
                target_id=lesson.id,
            )
    if report.sent == 0:
        await message.answer(tr(language, "lesson_delivery_failed"))
    elif report.failed or report.description_failed:
        await message.answer(
            tr(language, "lesson_delivery_partial", sent=report.sent, total=report.total)
        )


@router.callback_query(F.data.startswith("lesson:"))
async def reject_lesson_callback(callback: CallbackQuery, language: Language) -> None:
    await answer_callback_safely(callback, tr(language, "lesson_stale"), show_alert=True)
