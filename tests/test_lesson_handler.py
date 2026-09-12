from datetime import UTC, datetime
from unittest.mock import AsyncMock

from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.callbacks import UserLessonCallback
from app.bot.handlers import lessons as handler
from app.i18n import Language
from app.services.channels import add_channel
from app.services.lessons import LessonDeliveryReport, LessonVideoInput, create_lesson
from app.services.statistics import get_statistics_overview
from app.services.subscription import SubscriptionResult
from app.services.users import upsert_user, verify_phone


async def seed(database, *, verified: bool = True):
    async with database.session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=42,
            username="student",
            first_name="Student",
            last_name=None,
        )
        if verified:
            await verify_phone(session, 42, "+998901234567")
        await add_channel(
            session,
            telegram_chat_id="@lesson_channel",
            title="Lessons",
            join_url="https://t.me/lesson_channel",
        )
        return await create_lesson(
            session,
            title_uz="UZ",
            title_ru="RU",
            title_en="EN",
            text_uz="UZ text",
            text_ru="RU text",
            text_en="EN text",
            videos=(LessonVideoInput("file", "unique", "video.mp4"),),
        )


def lesson_callback(lesson_id: int) -> CallbackQuery:
    data = UserLessonCallback(action="select", lesson_id=lesson_id, page=0).pack()
    return CallbackQuery(
        id="callback",
        from_user=User(id=42, is_bot=False, first_name="Student"),
        chat_instance="private",
        message=Message(
            message_id=5,
            date=datetime.now(UTC),
            chat=Chat(id=42, type="private"),
            text="Lessons",
        ),
        data=data,
    )


async def test_successful_lesson_delivery_records_one_view(monkeypatch, database) -> None:
    lesson = await seed(database)

    async def answer(*_args, **_kwargs):
        return None

    async def subscribed(*_args, **_kwargs):
        return SubscriptionResult((), ())

    deliver = AsyncMock(return_value=LessonDeliveryReport(total=1, sent=1, failed=0))
    monkeypatch.setattr(handler, "answer_callback_safely", answer)
    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "deliver_lesson", deliver)

    await handler.select_lesson(
        lesson_callback(lesson.id),
        UserLessonCallback(action="select", lesson_id=lesson.id, page=0),
        AsyncMock(),
        Language.EN,
        database.session_factory,
    )

    deliver.assert_awaited_once()
    async with database.session_factory() as session:
        overview = await get_statistics_overview(session)
    assert overview.lesson_views == 1
    assert overview.lesson_viewers == 1


async def test_failed_lesson_delivery_does_not_record_view(monkeypatch, database) -> None:
    lesson = await seed(database)

    async def answer(*_args, **_kwargs):
        return None

    async def subscribed(*_args, **_kwargs):
        return SubscriptionResult((), ())

    async def message_answer(*_args, **_kwargs):
        return None

    monkeypatch.setattr(handler, "answer_callback_safely", answer)
    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(
        handler,
        "deliver_lesson",
        AsyncMock(return_value=LessonDeliveryReport(total=1, sent=0, failed=1)),
    )
    monkeypatch.setattr(Message, "answer", message_answer)

    await handler.select_lesson(
        lesson_callback(lesson.id),
        UserLessonCallback(action="select", lesson_id=lesson.id, page=0),
        AsyncMock(),
        Language.EN,
        database.session_factory,
    )

    async with database.session_factory() as session:
        overview = await get_statistics_overview(session)
    assert overview.lesson_views == 0
