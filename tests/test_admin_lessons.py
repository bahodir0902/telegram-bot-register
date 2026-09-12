from datetime import UTC, datetime

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.callbacks import AdminLessonCallback
from app.bot.handlers import admin_lessons as handler
from app.bot.states.admin import AdminLessonCreate
from app.i18n import Language
from app.services.lessons import get_lesson_videos, list_lessons


def state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=10, user_id=10),
    )


def callback() -> CallbackQuery:
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=10, type="private"),
        from_user=User(id=10, is_bot=False, first_name="Admin"),
        text="Draft",
    )
    return CallbackQuery(
        id="callback",
        from_user=User(id=10, is_bot=False, first_name="Admin"),
        chat_instance="private",
        message=message,
        data=AdminLessonCallback(action="create_save", lesson_id=0, page=0).pack(),
    )


async def test_save_lesson_draft_is_atomic_and_clears_state(monkeypatch, database) -> None:
    current_state = state()
    await current_state.set_state(AdminLessonCreate.waiting_for_videos)
    await current_state.update_data(
        title_uz="UZ title",
        title_ru="RU title",
        title_en="EN title",
        text_uz="UZ text",
        text_ru="RU text",
        text_en="EN text",
        videos=[
            {
                "telegram_file_id": "file-1",
                "telegram_file_unique_id": "unique-1",
                "original_filename": "one.mp4",
            },
            {
                "telegram_file_id": "file-2",
                "telegram_file_unique_id": "unique-2",
                "original_filename": "two.mp4",
            },
        ],
    )
    answers = []

    async def answer(*args, **kwargs):
        answers.append((args, kwargs))

    async def render(*_args, **_kwargs):
        return True

    monkeypatch.setattr(handler, "answer_callback_safely", answer)
    monkeypatch.setattr(handler, "render_lesson_detail", render)

    await handler.save_lesson_draft(
        callback(), current_state, Language.EN, database.session_factory
    )

    assert await current_state.get_state() is None
    async with database.session_factory() as session:
        lessons = await list_lessons(session, page=0)
        videos = await get_lesson_videos(session, lessons.items[0].id)
    assert lessons.total == 1
    assert [item.telegram_file_id for item in videos] == ["file-1", "file-2"]
    assert answers


async def test_incomplete_lesson_draft_writes_nothing(monkeypatch, database) -> None:
    current_state = state()
    await current_state.set_state(AdminLessonCreate.waiting_for_videos)
    await current_state.update_data(
        title_uz="UZ",
        title_ru="RU",
        title_en="EN",
        text_uz="UZ",
        text_ru="RU",
        text_en="EN",
        videos=[],
    )

    async def answer(*_args, **_kwargs):
        return None

    monkeypatch.setattr(handler, "answer_callback_safely", answer)
    await handler.save_lesson_draft(
        callback(), current_state, Language.EN, database.session_factory
    )

    assert await current_state.get_state() == AdminLessonCreate.waiting_for_videos.state
    async with database.session_factory() as session:
        lessons = await list_lessons(session, page=0)
    assert lessons.total == 0
