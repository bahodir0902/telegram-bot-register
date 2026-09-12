from __future__ import annotations

from datetime import UTC, datetime

from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.callbacks import UserOptionCallback
from app.bot.handlers import subscription as handler
from app.db.models import Channel, MediaType
from app.db.session import Database
from app.i18n import Language, tr
from app.services.channels import add_channel
from app.services.options import DeliveryReport, OptionItemInput, create_option, set_option_active
from app.services.subscription import SubscriptionResult
from app.services.users import (
    get_user,
    set_subscription_prompt,
    upsert_user,
    verify_phone,
)


def make_callback(
    *,
    data: str = "subscription:check",
    message_id: int = 99,
    chat_id: int = 42,
) -> CallbackQuery:
    sender = User(id=42, is_bot=False, first_name="Test")
    message = Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="private"),
        text="Prompt",
    )
    return CallbackQuery(
        id=f"callback-{message_id}-{data}",
        from_user=sender,
        chat_instance="private-instance",
        message=message,
        data=data,
    )


def option_callback(option_id: int, *, page: int = 0, chat_id: int = 42) -> CallbackQuery:
    data = UserOptionCallback(action="select", option_id=option_id, page=page).pack()
    return make_callback(data=data, chat_id=chat_id)


def option_list_message(language: Language = Language.EN) -> Message:
    return Message(
        message_id=200,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Test"),
        text=tr(language, "show_options"),
    )


async def seed_user(
    database: Database,
    *,
    verified: bool = True,
    prompt_id: int | None = None,
) -> None:
    async with database.session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=42,
            username=None,
            first_name="Test",
            last_name=None,
        )
        if verified:
            await verify_phone(session, 42, "+998901234567")
        if prompt_id is not None:
            await set_subscription_prompt(session, 42, prompt_id)


async def seed_channel(database: Database, suffix: str = "example") -> Channel:
    async with database.session_factory.begin() as session:
        return await add_channel(
            session,
            telegram_chat_id=f"@{suffix}_channel",
            title=suffix.title(),
            join_url=f"https://t.me/{suffix}_channel",
        )


async def seed_option(database: Database, label: str = "help"):
    async with database.session_factory.begin() as session:
        return await create_option(
            session,
            name_uz=f"uz-{label}",
            name_ru=f"ru-{label}",
            name_en=f"en-{label}",
            items=(
                OptionItemInput(
                    media_type=MediaType.TEXT,
                    telegram_file_id="",
                    telegram_file_unique_id=None,
                    original_filename=None,
                    text_uz=f"uz-content-{label}",
                    text_ru=f"ru-content-{label}",
                    text_en=f"en-content-{label}",
                ),
            ),
        )


def patch_common(monkeypatch):
    events: list[str] = []
    answers: list[str] = []
    edits: list[str] = []

    async def answer(*_args, **_kwargs):
        events.append("answer")

    async def answer_message(_message, text, **_kwargs):
        answers.append(text)

    async def edit(_message, text, **_kwargs):
        edits.append(text)

    monkeypatch.setattr(handler, "answer_callback_safely", answer)
    monkeypatch.setattr(Message, "answer", answer_message)
    monkeypatch.setattr(handler, "edit_text_safely", edit)
    return events, answers, edits


def patch_option_list_messages(monkeypatch):
    answers: list[str] = []
    status_message = Message(
        message_id=201,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=User(id=999, is_bot=True, first_name="Bot"),
        text="Checking",
    )

    async def answer_message(_message, text, **_kwargs):
        answers.append(text)
        return status_message

    monkeypatch.setattr(Message, "answer", answer_message)
    return answers, status_message


async def test_option_list_button_rechecks_membership_and_renders_first_page(
    monkeypatch, database: Database
) -> None:
    answers, status_message = patch_option_list_messages(monkeypatch)
    events: list[str] = []
    await seed_user(database)
    await seed_channel(database)
    await seed_option(database)

    async def subscribed(*_args, **_kwargs):
        events.append("check")
        return SubscriptionResult((), ())

    async def render(message, page, language, _session_factory):
        assert message is status_message
        events.append(f"render:{page}:{language.value}")

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "render_option_menu", render)
    await handler.show_option_list(
        option_list_message(), object(), Language.EN, database.session_factory
    )

    assert answers == [tr(Language.EN, "checking_subscription")]
    assert events == ["check", "render:0:en"]
    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None and user.subscription_verified_at is not None


async def test_option_list_button_restores_gate_when_membership_is_missing(
    monkeypatch, database: Database
) -> None:
    _, status_message = patch_option_list_messages(monkeypatch)
    restored: list[tuple[Message, str]] = []
    await seed_user(database)
    channel = await seed_channel(database)

    async def missing(*_args, **_kwargs):
        return SubscriptionResult((channel,), ())

    async def restore(message, _user_id, _channels, _language, _factory, *, text):
        restored.append((message, text))

    monkeypatch.setattr(handler, "check_subscriptions", missing)
    monkeypatch.setattr(handler, "restore_subscription_prompt", restore)
    await handler.show_option_list(
        option_list_message(), object(), Language.EN, database.session_factory
    )

    assert restored and restored[0][0] is status_message
    assert channel.title in restored[0][1]


async def test_option_list_button_api_failure_keeps_a_retryable_gate(
    monkeypatch, database: Database
) -> None:
    patch_option_list_messages(monkeypatch)
    restored: list[str] = []
    await seed_user(database)
    channel = await seed_channel(database)

    async def unavailable(*_args, **_kwargs):
        return SubscriptionResult((), (channel,))

    async def restore(_message, _user_id, _channels, _language, _factory, *, text):
        restored.append(text)

    monkeypatch.setattr(handler, "check_subscriptions", unavailable)
    monkeypatch.setattr(handler, "restore_subscription_prompt", restore)
    await handler.show_option_list(
        option_list_message(), object(), Language.EN, database.session_factory
    )

    assert restored == [tr(Language.EN, "subscription_check_error")]


async def test_option_list_button_rejects_unverified_user_without_network_check(
    monkeypatch, database: Database
) -> None:
    answers, _ = patch_option_list_messages(monkeypatch)
    await seed_user(database, verified=False)

    async def should_not_check(*_args, **_kwargs):
        raise AssertionError("subscription check must not run")

    monkeypatch.setattr(handler, "check_subscriptions", should_not_check)
    await handler.show_option_list(
        option_list_message(), object(), Language.EN, database.session_factory
    )

    assert answers == [tr(Language.EN, "option_registration_required")]


async def test_option_list_button_handles_channel_removal_during_check(
    monkeypatch, database: Database
) -> None:
    _, status_message = patch_option_list_messages(monkeypatch)
    edits: list[str] = []
    await seed_user(database)
    channel = await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        async with database.session_factory.begin() as session:
            await session.delete(await session.get(Channel, channel.id))
        return SubscriptionResult((), ())

    async def edit(message, text, **_kwargs):
        assert message is status_message
        edits.append(text)

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "edit_text_safely", edit)
    await handler.show_option_list(
        option_list_message(), object(), Language.EN, database.session_factory
    )

    assert edits == [tr(Language.EN, "subscription_no_channels")]


async def test_successful_subscription_transitions_to_menu_once_without_auto_content(
    monkeypatch, database: Database
) -> None:
    events, _, _ = patch_common(monkeypatch)

    async def subscribed(*_args, **_kwargs):
        events.append("check")
        return SubscriptionResult((), ())

    async def render(*_args, **_kwargs):
        events.append("menu")

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "render_option_menu", render)
    await seed_user(database, prompt_id=99)
    await seed_channel(database)

    callback = make_callback()
    await handler.check_subscription(callback, object(), Language.EN, database.session_factory)
    await handler.check_subscription(callback, object(), Language.EN, database.session_factory)

    assert events[0:2] == ["answer", "check"]
    assert events.count("check") == 2
    assert events.count("menu") == 1


async def test_channel_change_during_initial_check_requires_retry(
    monkeypatch, database: Database
) -> None:
    events, _, edits = patch_common(monkeypatch)

    async def subscribed(*_args, **_kwargs):
        await seed_channel(database, "second")
        return SubscriptionResult((), ())

    async def render(*_args, **_kwargs):
        events.append("menu")

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "render_option_menu", render)
    await seed_user(database, prompt_id=99)
    await seed_channel(database, "first")

    await handler.check_subscription(
        make_callback(), object(), Language.EN, database.session_factory
    )

    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None and user.subscription_prompt_message_id == 99
    assert not events.count("menu")
    assert any("channel list changed" in text for text in edits)


async def test_option_selection_rechecks_membership_and_delivers_current_language(
    monkeypatch, database: Database
) -> None:
    events, _, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        events.append("check")
        return SubscriptionResult((), ())

    async def deliver(_bot, user_id, items, language):
        events.append(f"deliver:{user_id}:{language.value}:{items[0].text_en}")
        return DeliveryReport(total=1, sent=1, failed=0)

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "deliver_option_items", deliver)

    await handler.select_option(
        option_callback(option.id),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert events[0] == "answer"
    assert "check" in events
    assert "deliver:42:en:en-content-help" in events


async def test_repeated_option_presses_each_require_a_new_live_check(
    monkeypatch, database: Database
) -> None:
    events, _, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        events.append("check")
        return SubscriptionResult((), ())

    async def deliver(*_args, **_kwargs):
        events.append("deliver")
        return DeliveryReport(total=1, sent=1, failed=0)

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "deliver_option_items", deliver)
    data = UserOptionCallback(action="select", option_id=option.id, page=0)
    callback = option_callback(option.id)
    await handler.select_option(callback, data, object(), Language.EN, database.session_factory)
    await handler.select_option(callback, data, object(), Language.EN, database.session_factory)
    assert events.count("check") == 2
    assert events.count("deliver") == 2


async def test_missing_membership_restores_subscription_prompt_and_blocks_delivery(
    monkeypatch, database: Database
) -> None:
    events, _, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    channel = await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        return SubscriptionResult((channel,), ())

    async def restore(*_args, **_kwargs):
        events.append("restore")

    async def deliver(*_args, **_kwargs):
        events.append("deliver")
        return DeliveryReport(total=1, sent=1, failed=0)

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "restore_subscription_prompt", restore)
    monkeypatch.setattr(handler, "deliver_option_items", deliver)
    await handler.select_option(
        option_callback(option.id),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert events.count("restore") == 1
    assert "deliver" not in events


async def test_membership_api_failure_keeps_menu_and_blocks_delivery(
    monkeypatch, database: Database
) -> None:
    events, _, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    channel = await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        return SubscriptionResult((), (channel,))

    async def render(*_args, **kwargs):
        events.append(f"render:{kwargs.get('prompt_key')}")

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "render_option_menu", render)
    await handler.select_option(
        option_callback(option.id),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert "render:option_check_error" in events


async def test_channel_change_during_option_check_restores_gate(
    monkeypatch, database: Database
) -> None:
    events, _, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    await seed_channel(database, "first")

    async def subscribed(*_args, **_kwargs):
        await seed_channel(database, "second")
        return SubscriptionResult((), ())

    async def restore(*_args, **_kwargs):
        events.append("restore")

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "restore_subscription_prompt", restore)
    await handler.select_option(
        option_callback(option.id),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert "restore" in events


async def test_inactive_or_deleted_option_refreshes_menu_without_network_check(
    monkeypatch, database: Database
) -> None:
    events, _, _ = patch_common(monkeypatch)
    await seed_user(database)
    await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        events.append("check")
        return SubscriptionResult((), ())

    async def render(*_args, **_kwargs):
        events.append("render")

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "render_option_menu", render)
    await handler.select_option(
        option_callback(999),
        UserOptionCallback(action="select", option_id=999, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert "render" in events and "check" not in events


async def test_unverified_user_cannot_use_forwarded_or_old_option_button(
    monkeypatch, database: Database
) -> None:
    _, answers, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database, verified=False)
    await seed_channel(database)
    await handler.select_option(
        option_callback(option.id),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert answers and "verify" in answers[-1].lower()


async def test_forwarded_option_menu_in_another_private_chat_is_ignored(
    monkeypatch, database: Database
) -> None:
    events, answers, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    await seed_channel(database)
    await handler.select_option(
        option_callback(option.id, chat_id=777),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert events == ["answer"] and not answers


async def test_partial_delivery_reports_counts_without_crashing(
    monkeypatch, database: Database
) -> None:
    _, answers, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        return SubscriptionResult((), ())

    async def deliver(*_args, **_kwargs):
        return DeliveryReport(total=3, sent=2, failed=1)

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "deliver_option_items", deliver)
    await handler.select_option(
        option_callback(option.id),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert answers and "2" in answers[-1] and "3" in answers[-1]


async def test_total_delivery_failure_returns_recoverable_message(
    monkeypatch, database: Database
) -> None:
    _, answers, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        return SubscriptionResult((), ())

    async def deliver(*_args, **_kwargs):
        return DeliveryReport(total=1, sent=0, failed=1)

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "deliver_option_items", deliver)
    await handler.select_option(
        option_callback(option.id),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert answers and "could not deliver" in answers[-1].lower()


async def test_verified_user_can_change_option_menu_page(monkeypatch, database: Database) -> None:
    events, _, _ = patch_common(monkeypatch)
    await seed_user(database)

    async def render(*_args, **_kwargs):
        events.append("render")

    monkeypatch.setattr(handler, "render_option_menu", render)
    callback_data = UserOptionCallback(action="page", option_id=0, page=2)
    await handler.change_option_page(
        make_callback(data=callback_data.pack()),
        callback_data,
        Language.EN,
        database.session_factory,
    )
    assert "render" in events


async def test_unverified_user_cannot_change_option_menu_page(
    monkeypatch, database: Database
) -> None:
    events, _, _ = patch_common(monkeypatch)
    await seed_user(database, verified=False)

    async def render(*_args, **_kwargs):
        events.append("render")

    monkeypatch.setattr(handler, "render_option_menu", render)
    callback_data = UserOptionCallback(action="page", option_id=0, page=2)
    await handler.change_option_page(
        make_callback(data=callback_data.pack()),
        callback_data,
        Language.EN,
        database.session_factory,
    )
    assert "render" not in events


async def test_initial_subscription_check_without_channels_is_recoverable(
    monkeypatch, database: Database
) -> None:
    events, _, edits = patch_common(monkeypatch)
    await seed_user(database, prompt_id=99)
    await handler.check_subscription(
        make_callback(), object(), Language.EN, database.session_factory
    )
    assert events == ["answer"]
    assert edits and "no subscription channel" in edits[-1].lower()


async def test_initial_check_requires_verified_phone_before_network_access(
    monkeypatch, database: Database
) -> None:
    events, answers, _ = patch_common(monkeypatch)
    await seed_user(database, verified=False, prompt_id=99)
    await seed_channel(database)

    async def should_not_check(*_args, **_kwargs):
        events.append("check")
        return SubscriptionResult((), ())

    monkeypatch.setattr(handler, "check_subscriptions", should_not_check)
    await handler.check_subscription(
        make_callback(), object(), Language.EN, database.session_factory
    )
    assert events == ["answer"]
    assert answers and "verify" in answers[-1].lower()


async def test_initial_check_ignores_forwarded_or_group_callback(
    monkeypatch, database: Database
) -> None:
    events, _, edits = patch_common(monkeypatch)
    await seed_user(database, prompt_id=99)
    await seed_channel(database)
    await handler.check_subscription(
        make_callback(chat_id=777), object(), Language.EN, database.session_factory
    )
    assert events == ["answer"]
    assert not edits
    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None and user.subscription_prompt_message_id == 99


async def test_initial_missing_membership_keeps_gate_and_lists_channel(
    monkeypatch, database: Database
) -> None:
    events, _, edits = patch_common(monkeypatch)
    await seed_user(database, prompt_id=99)
    channel = await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        return SubscriptionResult((channel,), ())

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    await handler.check_subscription(
        make_callback(), object(), Language.EN, database.session_factory
    )
    assert events == ["answer"]
    assert edits and channel.title in edits[-1]
    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None and user.subscription_prompt_message_id == 99


async def test_initial_membership_api_failure_keeps_gate(monkeypatch, database: Database) -> None:
    events, _, edits = patch_common(monkeypatch)
    await seed_user(database, prompt_id=99)
    channel = await seed_channel(database)

    async def unavailable(*_args, **_kwargs):
        return SubscriptionResult((), (channel,))

    monkeypatch.setattr(handler, "check_subscriptions", unavailable)
    await handler.check_subscription(
        make_callback(), object(), Language.EN, database.session_factory
    )
    assert events == ["answer"]
    assert edits and "could not check" in edits[-1].lower()


async def test_render_option_menu_handles_empty_and_normalized_page(
    monkeypatch, database: Database
) -> None:
    _, _, edits = patch_common(monkeypatch)
    message = make_callback().message
    assert isinstance(message, Message)
    await handler.render_option_menu(message, 99, Language.EN, database.session_factory)
    assert "no active recipes" in edits[-1].lower()
    await seed_option(database, "one")
    await handler.render_option_menu(message, 99, Language.EN, database.session_factory)
    assert "Page: 1/1" in edits[-1]


async def test_restore_subscription_prompt_persists_new_message_id(
    monkeypatch, database: Database
) -> None:
    patch_common(monkeypatch)
    await seed_user(database)
    channel = await seed_channel(database)
    message = make_callback(message_id=123).message
    assert isinstance(message, Message)
    await handler.restore_subscription_prompt(
        message,
        42,
        (channel,),
        Language.EN,
        database.session_factory,
        text="retry",
    )
    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None and user.subscription_prompt_message_id == 123


async def test_option_disabled_during_live_check_is_not_delivered(
    monkeypatch, database: Database
) -> None:
    events, _, _ = patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        async with database.session_factory.begin() as session:
            await set_option_active(session, option.id, False)
        return SubscriptionResult((), ())

    async def render(*_args, **_kwargs):
        events.append("render")

    async def deliver(*_args, **_kwargs):
        events.append("deliver")
        return DeliveryReport(total=1, sent=1, failed=0)

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "render_option_menu", render)
    monkeypatch.setattr(handler, "deliver_option_items", deliver)
    await handler.select_option(
        option_callback(option.id),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    assert "render" in events and "deliver" not in events


async def test_successful_option_selection_records_latest_subscription_verification(
    monkeypatch, database: Database
) -> None:
    patch_common(monkeypatch)
    option = await seed_option(database)
    await seed_user(database)
    await seed_channel(database)

    async def subscribed(*_args, **_kwargs):
        return SubscriptionResult((), ())

    async def deliver(*_args, **_kwargs):
        return DeliveryReport(total=1, sent=1, failed=0)

    monkeypatch.setattr(handler, "check_subscriptions", subscribed)
    monkeypatch.setattr(handler, "deliver_option_items", deliver)
    await handler.select_option(
        option_callback(option.id),
        UserOptionCallback(action="select", option_id=option.id, page=0),
        object(),
        Language.EN,
        database.session_factory,
    )
    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None and user.subscription_verified_at is not None
