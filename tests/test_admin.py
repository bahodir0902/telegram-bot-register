import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, User, Video

from app.bot.albums import AlbumCollector
from app.bot.filters.admin import AdminFilter, is_admin_user
from app.bot.handlers import admin as admin_handler
from app.bot.states.admin import AdminBroadcast
from app.config import Settings
from app.i18n import Language


def test_admin_authorization_uses_configured_sender_id(settings: Settings) -> None:
    assert is_admin_user(10, settings.admin_ids)
    assert not is_admin_user(99, settings.admin_ids)
    assert not is_admin_user(None, settings.admin_ids)


async def test_admin_filter(settings: Settings) -> None:
    event = type("Event", (), {"from_user": User(id=20, is_bot=False, first_name="A")})()
    assert await AdminFilter()(event, settings)


def make_admin_message(text: str) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=10, type="private"),
        from_user=User(id=10, is_bot=False, first_name="Admin"),
        text=text,
    )


def make_admin_video(message_id: int, group_id: str) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=10, type="private"),
        from_user=User(id=10, is_bot=False, first_name="Admin"),
        video=Video(
            file_id=f"file-{message_id}",
            file_unique_id=f"unique-{message_id}",
            width=100,
            height=100,
            duration=1,
        ),
        media_group_id=group_id,
    )


def make_state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=10, user_id=10),
    )


async def test_broadcast_composition_previews_current_admin_language(monkeypatch) -> None:
    async def answer(*_args, **_kwargs) -> None:
        pass

    monkeypatch.setattr(Message, "answer", answer)
    state = make_state()
    await state.update_data(purpose="broadcast", request_token="token")
    await state.set_state(AdminBroadcast.waiting_for_content)
    bot = AsyncMock()

    await admin_handler.receive_admin_content(make_admin_message("O‘zbekcha"), state, Language.EN)
    await admin_handler.receive_ru_content(make_admin_message("Русский"), state, Language.EN)
    await admin_handler.receive_en_content(
        make_admin_message("English"),
        bot,
        state,
        Language.EN,
        object(),
    )

    assert await state.get_state() == AdminBroadcast.waiting_for_confirmation.state
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[:2] == (10, "English")


async def test_broadcast_oversized_text_is_rejected_without_losing_state(monkeypatch) -> None:
    answers: list[str] = []

    async def answer(_message, text, **_kwargs) -> None:
        answers.append(text)

    monkeypatch.setattr(Message, "answer", answer)
    state = make_state()
    await state.set_state(AdminBroadcast.waiting_for_content)

    await admin_handler.receive_admin_content(make_admin_message("x" * 10001), state, Language.EN)

    assert await state.get_state() == AdminBroadcast.waiting_for_content.state
    assert any("10000" in text for text in answers)


async def test_broadcast_album_is_rejected_once_without_corrupting_state(monkeypatch) -> None:
    answers: list[str] = []

    async def answer(_message, text, **_kwargs) -> None:
        answers.append(text)

    monkeypatch.setattr(Message, "answer", answer)
    monkeypatch.setattr(admin_handler, "album_collector", AlbumCollector(debounce_seconds=0.01))
    state = make_state()
    await state.set_state(AdminBroadcast.waiting_for_content)
    await asyncio.gather(
        admin_handler.receive_admin_content(make_admin_video(1, "album"), state, Language.EN),
        admin_handler.receive_admin_content(make_admin_video(2, "album"), state, Language.EN),
    )
    assert await state.get_state() == AdminBroadcast.waiting_for_content.state
    assert len(answers) == 1
    assert "album" in answers[0].lower()
