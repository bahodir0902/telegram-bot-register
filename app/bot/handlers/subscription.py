from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import SubscriptionCallback
from app.bot.keyboards.user import subscription_keyboard
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.config import Settings
from app.db.session import AsyncSessionFactory
from app.services.media import deliver_active_media
from app.services.subscription import SubscriptionCheckError, is_subscribed
from app.services.users import claim_subscription_prompt, get_user

logger = logging.getLogger(__name__)
router = Router(name="subscription")


@router.callback_query(SubscriptionCallback.filter(F.action == "check"))
async def check_subscription(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback, "Checking subscription…")

    sender = callback.from_user
    message = callback.message
    if sender is None or not isinstance(message, Message):
        return

    try:
        subscribed = await is_subscribed(bot, settings.channel_id, sender.id)
    except SubscriptionCheckError:
        logger.warning(
            "Channel membership check failed",
            extra={"user_id": sender.id, "channel_id": settings.channel_id},
            exc_info=True,
        )
        try:
            await edit_text_safely(
                message,
                "⚠️ I could not check the channel right now. Please try again shortly.",
                reply_markup=subscription_keyboard(settings.channel_url),
            )
        except TelegramAPIError:
            logger.warning("Could not update subscription prompt", exc_info=True)
        return

    if not subscribed:
        try:
            await edit_text_safely(
                message,
                "📢 You are not subscribed yet. Join the channel, then check again.",
                reply_markup=subscription_keyboard(settings.channel_url),
            )
        except TelegramAPIError:
            logger.warning("Could not update subscription prompt", exc_info=True)
        return

    async with session_factory.begin() as session:
        user = await get_user(session, sender.id)
        claimed = user is not None and await claim_subscription_prompt(
            session, sender.id, message.message_id
        )

    try:
        await edit_text_safely(message, "✅ <b>Subscription confirmed!</b>")
    except TelegramAPIError:
        logger.warning("Could not mark subscription prompt complete", exc_info=True)

    if not claimed:
        return

    report = await deliver_active_media(bot, sender.id, session_factory)
    if report.total == 0:
        await message.answer("There is no active media available right now.")
    elif report.sent == 0:
        await message.answer(
            "I could not deliver the available media right now. Please try again later."
        )


@router.callback_query(F.data.startswith("subscription:"))
async def reject_subscription_callback(callback: CallbackQuery) -> None:
    await answer_callback_safely(
        callback,
        "This subscription action is no longer valid. Send /start to get a new prompt.",
        show_alert=True,
    )
