from __future__ import annotations

from datetime import UTC, datetime

from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.handlers import subscription as handler
from app.config import Settings
from app.db.session import Database
from app.services.media import DeliveryReport
from app.services.users import set_subscription_prompt, upsert_user


def make_callback() -> CallbackQuery:
    sender = User(id=42, is_bot=False, first_name="Test")
    message = Message(
        message_id=99,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        text="Subscription prompt",
    )
    return CallbackQuery(
        id="callback-id",
        from_user=sender,
        chat_instance="private-instance",
        message=message,
        data="subscription:check",
    )


async def test_callback_is_answered_first_and_double_click_does_not_redeliver(
    monkeypatch,
    database: Database,
    settings: Settings,
) -> None:
    events: list[str] = []

    async def answer(*args, **kwargs) -> None:
        events.append("answer")

    async def subscribed(*args, **kwargs) -> bool:
        events.append("check")
        return True

    async def edit(*args, **kwargs) -> None:
        events.append("edit")

    async def deliver(*args, **kwargs) -> DeliveryReport:
        events.append("deliver")
        return DeliveryReport(total=1, sent=1, failed=0)

    monkeypatch.setattr(handler, "answer_callback_safely", answer)
    monkeypatch.setattr(handler, "is_subscribed", subscribed)
    monkeypatch.setattr(handler, "edit_text_safely", edit)
    monkeypatch.setattr(handler, "deliver_active_media", deliver)

    async with database.session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=42,
            username=None,
            first_name="Test",
            last_name=None,
        )
        await set_subscription_prompt(session, 42, 99)

    callback = make_callback()
    bot = object()
    await handler.check_subscription(callback, bot, settings, database.session_factory)
    await handler.check_subscription(callback, bot, settings, database.session_factory)

    assert events[0:2] == ["answer", "check"]
    assert events.count("check") == 2
    assert events.count("deliver") == 1
