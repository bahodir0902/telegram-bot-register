from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import SubscriptionCallback, UserOptionCallback
from app.bot.keyboards.user import options_keyboard, subscription_keyboard
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.db.models import Channel, EngagementKind
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr, translated_values
from app.services.channels import channel_signature, get_channels
from app.services.options import (
    deliver_option_items,
    get_option,
    get_option_items,
    list_options,
)
from app.services.statistics import record_engagement
from app.services.subscription import check_subscriptions
from app.services.users import (
    claim_subscription_prompt,
    get_user,
    mark_subscription_verified,
    set_subscription_prompt,
)

logger = logging.getLogger(__name__)
router = Router(name="subscription")


async def render_option_menu(
    message: Message,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
    *,
    prompt_key: str = "options_prompt",
) -> None:
    async with session_factory() as session:
        result = await list_options(session, page=page, page_size=8, active_only=True)
    if not result.items:
        await edit_text_safely(message, tr(language, "options_empty"))
        return
    await edit_text_safely(
        message,
        tr(
            language,
            prompt_key,
            page=result.page + 1,
            pages=result.pages,
        ),
        reply_markup=options_keyboard(result, language),
    )


async def restore_subscription_prompt(
    message: Message,
    user_id: int,
    channels: tuple[Channel, ...],
    language: Language,
    session_factory: AsyncSessionFactory,
    *,
    text: str,
) -> None:
    await edit_text_safely(
        message,
        text,
        reply_markup=subscription_keyboard(channels, language),
    )
    async with session_factory.begin() as session:
        await set_subscription_prompt(session, user_id, message.message_id)


@router.message(
    F.text.in_(translated_values("show_options")),
    F.chat.type == ChatType.PRIVATE,
)
async def show_option_list(
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
        channels = await get_channels(session)
        initial_signature = await channel_signature(session)
    if user is None or user.phone_verified_at is None:
        await message.answer(tr(language, "option_registration_required"))
        return

    status_message = await message.answer(tr(language, "checking_subscription"))
    if not channels:
        await edit_text_safely(status_message, tr(language, "subscription_no_channels"))
        return

    result = await check_subscriptions(bot, channels, sender.id)
    if result.failed:
        logger.warning(
            "Option-list membership checks failed",
            extra={
                "user_id": sender.id,
                "channel_ids": [item.telegram_chat_id for item in result.failed],
            },
        )
        async with session_factory() as session:
            current_channels = await get_channels(session)
        await restore_subscription_prompt(
            status_message,
            sender.id,
            current_channels or channels,
            language,
            session_factory,
            text=tr(language, "subscription_check_error"),
        )
        return

    if result.missing:
        missing = "\n".join(f"• {escape(item.title)}" for item in result.missing)
        async with session_factory() as session:
            current_channels = await get_channels(session)
        await restore_subscription_prompt(
            status_message,
            sender.id,
            current_channels or channels,
            language,
            session_factory,
            text=tr(language, "subscription_missing", channels=missing),
        )
        return

    async with session_factory() as session:
        current_channels = await get_channels(session)
        current_signature = await channel_signature(session)
    if current_signature != initial_signature:
        if current_channels:
            await restore_subscription_prompt(
                status_message,
                sender.id,
                current_channels,
                language,
                session_factory,
                text=tr(language, "subscription_channels_changed"),
            )
        else:
            await edit_text_safely(status_message, tr(language, "subscription_no_channels"))
        return

    async with session_factory.begin() as session:
        await mark_subscription_verified(session, sender.id)
    await render_option_menu(status_message, 0, language, session_factory)


@router.callback_query(SubscriptionCallback.filter(F.action == "check"))
async def check_subscription(
    callback: CallbackQuery,
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

    async with session_factory() as session:
        user = await get_user(session, sender.id)
        channels = await get_channels(session)
        initial_signature = await channel_signature(session)
    if user is None or user.phone_verified_at is None:
        await message.answer(tr(language, "option_registration_required"))
        return
    if not channels:
        try:
            await edit_text_safely(message, tr(language, "subscription_no_channels"))
        except TelegramAPIError:
            logger.warning("Could not update empty subscription prompt", exc_info=True)
        return

    result = await check_subscriptions(bot, channels, sender.id)
    if result.failed:
        logger.warning(
            "Channel membership checks failed",
            extra={
                "user_id": sender.id,
                "channel_ids": [item.telegram_chat_id for item in result.failed],
            },
        )
        async with session_factory() as session:
            current_channels = await get_channels(session)
        try:
            await edit_text_safely(
                message,
                tr(language, "subscription_check_error"),
                reply_markup=subscription_keyboard(current_channels or channels, language),
            )
        except TelegramAPIError:
            logger.warning("Could not update subscription prompt", exc_info=True)
        return

    if result.missing:
        missing = "\n".join(f"• {escape(item.title)}" for item in result.missing)
        async with session_factory() as session:
            current_channels = await get_channels(session)
        try:
            await edit_text_safely(
                message,
                tr(language, "subscription_missing", channels=missing),
                reply_markup=subscription_keyboard(current_channels or channels, language),
            )
        except TelegramAPIError:
            logger.warning("Could not update subscription prompt", exc_info=True)
        return

    async with session_factory() as session:
        current_channels = await get_channels(session)
        current_signature = await channel_signature(session)
    if current_signature != initial_signature:
        try:
            await edit_text_safely(
                message,
                tr(language, "subscription_channels_changed"),
                reply_markup=subscription_keyboard(current_channels, language),
            )
        except TelegramAPIError:
            logger.warning("Could not refresh changed subscription prompt", exc_info=True)
        return

    async with session_factory.begin() as session:
        claimed = await claim_subscription_prompt(session, sender.id, message.message_id)

    if not claimed:
        return
    try:
        await render_option_menu(message, 0, language, session_factory)
    except TelegramAPIError:
        logger.warning("Could not render option menu", exc_info=True)


@router.callback_query(UserOptionCallback.filter(F.action == "page"))
async def change_option_page(
    callback: CallbackQuery,
    callback_data: UserOptionCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    sender = callback.from_user
    message = callback.message
    if sender is None or not isinstance(message, Message):
        return
    if message.chat.type != ChatType.PRIVATE or message.chat.id != sender.id:
        return
    async with session_factory() as session:
        user = await get_user(session, sender.id)
    if user is None or user.phone_verified_at is None:
        return
    await render_option_menu(message, callback_data.page, language, session_factory)


@router.callback_query(UserOptionCallback.filter(F.action == "select"))
async def select_option(
    callback: CallbackQuery,
    callback_data: UserOptionCallback,
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

    async with session_factory() as session:
        user = await get_user(session, sender.id)
        option = await get_option(session, callback_data.option_id)
        items = (
            await get_option_items(session, callback_data.option_id)
            if option is not None and option.is_active
            else ()
        )
        channels = await get_channels(session)
        initial_signature = await channel_signature(session)
    if user is None or user.phone_verified_at is None:
        await message.answer(tr(language, "option_registration_required"))
        return
    if option is None or not option.is_active or not items:
        await render_option_menu(message, callback_data.page, language, session_factory)
        return
    if not channels:
        await edit_text_safely(message, tr(language, "subscription_no_channels"))
        return

    result = await check_subscriptions(bot, channels, sender.id)
    if result.failed:
        logger.warning(
            "Option membership checks failed",
            extra={
                "user_id": sender.id,
                "channel_ids": [item.telegram_chat_id for item in result.failed],
            },
        )
        await render_option_menu(
            message,
            callback_data.page,
            language,
            session_factory,
            prompt_key="option_check_error",
        )
        return
    if result.missing:
        missing = "\n".join(f"• {escape(item.title)}" for item in result.missing)
        async with session_factory() as session:
            current_channels = await get_channels(session)
        await restore_subscription_prompt(
            message,
            sender.id,
            current_channels or channels,
            language,
            session_factory,
            text=tr(language, "subscription_missing", channels=missing),
        )
        return

    async with session_factory() as session:
        current_channels = await get_channels(session)
        current_signature = await channel_signature(session)
        current_option = await get_option(session, callback_data.option_id)
        current_items = (
            await get_option_items(session, callback_data.option_id)
            if current_option is not None and current_option.is_active
            else ()
        )
    if current_signature != initial_signature:
        await restore_subscription_prompt(
            message,
            sender.id,
            current_channels,
            language,
            session_factory,
            text=tr(language, "subscription_channels_changed"),
        )
        return
    if current_option is None or not current_option.is_active or not current_items:
        await render_option_menu(message, callback_data.page, language, session_factory)
        return

    async with session_factory.begin() as session:
        await mark_subscription_verified(session, sender.id)
    report = await deliver_option_items(bot, sender.id, current_items, language)
    if report.sent:
        async with session_factory.begin() as session:
            await record_engagement(
                session,
                telegram_id=sender.id,
                kind=EngagementKind.RECIPE,
                target_id=current_option.id,
            )
    if report.sent == 0:
        await message.answer(tr(language, "option_delivery_failed"))
    elif report.failed:
        await message.answer(
            tr(
                language,
                "option_delivery_partial",
                sent=report.sent,
                total=report.total,
            )
        )


@router.callback_query(F.data.startswith("subscription:"))
async def reject_subscription_callback(callback: CallbackQuery, language: Language) -> None:
    await answer_callback_safely(
        callback,
        tr(language, "subscription_stale"),
        show_alert=True,
    )


@router.callback_query(F.data.startswith("choice:"))
async def reject_option_callback(callback: CallbackQuery, language: Language) -> None:
    await answer_callback_safely(
        callback,
        tr(language, "option_stale"),
        show_alert=True,
    )
