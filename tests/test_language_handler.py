from datetime import UTC, datetime

from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.callbacks import LanguageCallback
from app.bot.handlers import language as language_handler
from app.bot.handlers import start as start_handler
from app.db.session import Database
from app.i18n import Language, tr
from app.services.users import get_user, set_user_language, upsert_user, verify_phone


def make_message() -> Message:
    sender = User(id=42, is_bot=False, first_name="Test")
    return Message(
        message_id=10,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=sender,
        text="/start",
    )


def make_language_callback() -> CallbackQuery:
    return CallbackQuery(
        id="language-callback",
        from_user=User(id=42, is_bot=False, first_name="Test"),
        chat_instance="private",
        message=make_message(),
        data="language:ru",
    )


async def test_start_requires_language_then_uses_persisted_choice(
    monkeypatch, database: Database
) -> None:
    selected: list[Language] = []
    continued: list[Language] = []

    async def show_selector(_message, language) -> None:
        selected.append(language)

    async def continue_flow(_message, _sender, language, _session_factory) -> None:
        continued.append(language)

    monkeypatch.setattr(start_handler, "send_language_selector", show_selector)
    monkeypatch.setattr(start_handler, "continue_onboarding", continue_flow)

    message = make_message()
    await start_handler.start_private(message, Language.UZ, database.session_factory)
    assert selected == [Language.UZ]
    assert continued == []

    async with database.session_factory.begin() as session:
        await set_user_language(session, 42, Language.RU)
    await start_handler.start_private(message, Language.UZ, database.session_factory)
    assert continued == [Language.RU]


async def test_language_callback_persists_first_choice_and_resumes_onboarding(
    monkeypatch, database: Database
) -> None:
    continued: list[Language] = []

    async def answer(*_args, **_kwargs) -> None:
        pass

    async def continue_flow(_message, _sender, language, _session_factory) -> None:
        continued.append(language)

    monkeypatch.setattr(language_handler, "answer_callback_safely", answer)
    monkeypatch.setattr(language_handler, "continue_onboarding", continue_flow)

    callback = make_language_callback()
    await language_handler.set_language(
        callback,
        LanguageCallback(code=Language.RU.value),
        database.session_factory,
    )

    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None
    assert user.language_code == Language.RU
    assert continued == [Language.RU]


async def test_existing_language_switch_does_not_restart_onboarding(
    monkeypatch, database: Database
) -> None:
    answers: list[tuple[str, dict[str, object]]] = []
    continued: list[Language] = []

    async def answer_callback(*_args, **_kwargs) -> None:
        pass

    async def answer_message(_message, text, **_kwargs) -> None:
        answers.append((text, _kwargs))

    async def continue_flow(_message, _sender, language, _session_factory) -> None:
        continued.append(language)

    async with database.session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=42,
            username=None,
            first_name="Test",
            last_name=None,
        )
        await set_user_language(session, 42, Language.EN)

    monkeypatch.setattr(language_handler, "answer_callback_safely", answer_callback)
    monkeypatch.setattr(language_handler, "continue_onboarding", continue_flow)
    monkeypatch.setattr(Message, "answer", answer_message)

    await language_handler.set_language(
        make_language_callback(),
        LanguageCallback(code=Language.RU.value),
        database.session_factory,
    )

    assert continued == []
    assert answers
    keyboard = answers[-1][1]["reply_markup"]
    assert keyboard.keyboard[1][0].text == tr(Language.RU, "show_options")
    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None
    assert user.language_code == Language.RU


async def test_verified_onboarding_exposes_localized_option_list_button(
    monkeypatch, database: Database
) -> None:
    answers: list[dict[str, object]] = []

    async def answer_message(_message, _text, **kwargs):
        answers.append(kwargs)
        return make_message()

    async def send_gate(*_args, **_kwargs) -> None:
        pass

    async with database.session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=42,
            username=None,
            first_name="Test",
            last_name=None,
        )
        await set_user_language(session, 42, Language.RU)
        await verify_phone(session, 42, "+998901234567")

    monkeypatch.setattr(Message, "answer", answer_message)
    monkeypatch.setattr(start_handler, "send_subscription_prompt", send_gate)
    message = make_message()
    assert message.from_user is not None
    await start_handler.continue_onboarding(
        message,
        message.from_user,
        Language.RU,
        database.session_factory,
    )

    keyboard = answers[0]["reply_markup"]
    assert keyboard.keyboard[1][0].text == tr(Language.RU, "show_options")
