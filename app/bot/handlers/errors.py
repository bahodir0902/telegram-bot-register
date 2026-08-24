from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from app.bot.messages import answer_callback_safely
from app.i18n import DEFAULT_LANGUAGE, Language, tr

logger = logging.getLogger(__name__)


async def handle_update_error(event: ErrorEvent, language: Language = DEFAULT_LANGUAGE) -> bool:
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
            tr(language, "generic_action_error"),
            show_alert=True,
        )
        return True

    message = event.update.message
    if message is not None:
        try:
            await message.answer(tr(language, "generic_error"))
        except TelegramAPIError:
            logger.warning("Could not send update error notice", exc_info=True)
    return True
