from datetime import UTC, datetime

from aiogram.types import Chat, Message, User

from app.bot.middleware import UserLanguageMiddleware
from app.db.session import Database
from app.i18n import Language
from app.services.users import (
    get_user,
    mark_user_unreachable,
    set_user_language,
    upsert_user,
)


async def test_any_returning_message_reactivates_unreachable_user(
    database: Database,
) -> None:
    async with database.session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=42,
            username=None,
            first_name="User",
            last_name=None,
        )
        await set_user_language(session, 42, Language.RU)
        await mark_user_unreachable(session, 42)

    captured: dict[str, object] = {}

    async def handler(_event, data):
        captured.update(data)

    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="User"),
        text="hello again",
    )
    await UserLanguageMiddleware()(
        handler,
        message,
        {"session_factory": database.session_factory},
    )

    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert captured["language"] == Language.RU
    assert user is not None and user.is_reachable
