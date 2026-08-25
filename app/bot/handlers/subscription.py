from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import SubscriptionCallback
from app.bot.keyboards.user import subscription_keyboard
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr
from app.services.channels import channel_signature, get_channels
from app.services.media import deliver_active_media
from app.services.subscription import check_subscriptions
from app.services.users import claim_subscription_prompt, get_user

logger = logging.getLogger(__name__)
router = Router(name="subscription")


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

    async with session_factory() as session:
        channels = await get_channels(session)
        initial_signature = await channel_signature(session)
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
        user = await get_user(session, sender.id)
        claimed = user is not None and await claim_subscription_prompt(
            session, sender.id, message.message_id
        )

    try:
        await edit_text_safely(message, tr(language, "subscription_confirmed"))
    except TelegramAPIError:
        logger.warning("Could not mark subscription prompt complete", exc_info=True)

    if not claimed:
        return

    report = await deliver_active_media(bot, sender.id, session_factory, language)
    if report.total == 0:
        await message.answer(tr(language, "no_active_media"))
    elif report.sent == 0:
        await message.answer(tr(language, "media_delivery_failed"))


@router.callback_query(F.data.startswith("subscription:"))
async def reject_subscription_callback(callback: CallbackQuery, language: Language) -> None:
    await answer_callback_safely(
        callback,
        tr(language, "subscription_stale"),
        show_alert=True,
    )
