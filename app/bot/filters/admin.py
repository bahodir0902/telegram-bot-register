from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import Settings


def is_admin_user(user_id: int | None, admin_ids: frozenset[int]) -> bool:
    return user_id is not None and user_id in admin_ids


class AdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        sender_id = event.from_user.id if event.from_user is not None else None
        return is_admin_user(sender_id, settings.admin_ids)
