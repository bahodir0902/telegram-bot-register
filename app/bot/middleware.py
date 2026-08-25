from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.i18n import DEFAULT_LANGUAGE
from app.services.users import get_user, mark_user_reachable


class UserLanguageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        language = DEFAULT_LANGUAGE
        session_factory = data.get("session_factory")
        sender = event.from_user if isinstance(event, (Message, CallbackQuery)) else None
        if sender is not None and session_factory is not None:
            async with session_factory() as session:
                user = await get_user(session, sender.id)
            if user is not None:
                language = user.language_code or DEFAULT_LANGUAGE
                if isinstance(event, Message) and not user.is_reachable:
                    async with session_factory.begin() as session:
                        await mark_user_reachable(session, sender.id)
        data["language"] = language
        return await handler(event, data)
