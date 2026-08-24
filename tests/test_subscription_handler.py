from __future__ import annotations

from datetime import UTC, datetime

from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.handlers import subscription as handler
from app.config import Settings
from app.db.models import Channel
from app.db.session import Database
from app.i18n import Language
from app.services.channels import add_channel
from app.services.media import DeliveryReport
from app.services.subscription import SubscriptionResult
from app.services.users import get_user, set_subscription_prompt, upsert_user


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

    async def subscribed(*args, **kwargs) -> SubscriptionResult:
        events.append("check")
        return SubscriptionResult((), ())

    async def edit(*args, **kwargs) -> None:
        events.append("edit")

    async def deliver(*args, **kwargs) -> DeliveryReport:
        events.append("deliver")
        return DeliveryReport(total=1, sent=1, failed=0)

    monkeypatch.setattr(handler, "answer_callback_safely", answer)
    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
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
        session.add(
            Channel(
                telegram_chat_id="@example_channel",
                title="Example",
                join_url="https://t.me/example_channel",
            )
        )

    callback = make_callback()
    bot = object()
    await handler.check_subscription(callback, bot, Language.EN, database.session_factory)
    await handler.check_subscription(callback, bot, Language.EN, database.session_factory)

    assert events[0:2] == ["answer", "check"]
    assert events.count("check") == 2
    assert events.count("deliver") == 1


async def test_channel_change_during_check_requires_retry(
    monkeypatch,
    database: Database,
) -> None:
    edits: list[str] = []
    delivered = False

    async def answer(*args, **kwargs) -> None:
        pass

    async def subscribed(*args, **kwargs) -> SubscriptionResult:
        async with database.session_factory.begin() as session:
            await add_channel(
                session,
                telegram_chat_id="@second_channel",
                title="Second",
                join_url="https://t.me/second_channel",
            )
        return SubscriptionResult((), ())

    async def edit(_message, text, **kwargs) -> None:
        edits.append(text)

    async def deliver(*args, **kwargs) -> DeliveryReport:
        nonlocal delivered
        delivered = True
        return DeliveryReport(total=1, sent=1, failed=0)

    monkeypatch.setattr(handler, "answer_callback_safely", answer)
    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
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
        await add_channel(
            session,
            telegram_chat_id="@first_channel",
            title="First",
            join_url="https://t.me/first_channel",
        )

    await handler.check_subscription(
        make_callback(), object(), Language.EN, database.session_factory
    )

    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None
    assert user.subscription_prompt_message_id == 99
    assert not delivered
    assert any("channel list changed" in text for text in edits)
