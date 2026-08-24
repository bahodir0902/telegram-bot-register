from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from app.bot.messages import answer_callback_safely

logger = logging.getLogger(__name__)


async def handle_update_error(event: ErrorEvent) -> bool:
    """Log unexpected boundary failures without exposing internals to Telegram users."""

    error = event.exception
    logger.error(
        "Unhandled error while processing Telegram update",
        exc_info=(type(error), error, error.__traceback__),
    )

    callback = event.update.callback_query
    if callback is not None:
        await answer_callback_safely(
            callback,
            "The action could not be completed. Please try again.",
            show_alert=True,
        )
        return True

    message = event.update.message
    if message is not None:
        try:
            await message.answer("Something went wrong. Please try again shortly.")
        except TelegramAPIError:
            logger.warning("Could not send update error notice", exc_info=True)
    return True
