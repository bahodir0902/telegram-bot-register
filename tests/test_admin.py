from aiogram.types import User

from app.bot.filters.admin import AdminFilter, is_admin_user
from app.config import Settings


def test_admin_authorization_uses_configured_sender_id(settings: Settings) -> None:
    assert is_admin_user(10, settings.admin_ids)
    assert not is_admin_user(99, settings.admin_ids)
    assert not is_admin_user(None, settings.admin_ids)


async def test_admin_filter(settings: Settings) -> None:
    event = type("Event", (), {"from_user": User(id=20, is_bot=False, first_name="A")})()
    assert await AdminFilter()(event, settings)
