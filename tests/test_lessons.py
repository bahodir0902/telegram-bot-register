from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendVideo

from app.db.models import VideoLesson
from app.i18n import Language
from app.services.lessons import (
    EmptyLessonError,
    LessonVideoInput,
    create_lesson,
    delete_lesson_video,
    deliver_lesson,
    get_lesson,
    get_lesson_videos,
    list_lessons,
    move_lesson_video,
    set_lesson_active,
)


def video(number: int) -> LessonVideoInput:
    return LessonVideoInput(
        telegram_file_id=f"file-{number}",
        telegram_file_unique_id=f"unique-{number}",
        original_filename=f"video-{number}.mp4",
    )


async def make_lesson(database, *videos: LessonVideoInput, text: str = "Description"):
    async with database.session_factory.begin() as session:
        return await create_lesson(
            session,
            title_uz="Sarlavha",
            title_ru="Цитрамон",
            title_en="Citramon",
            text_uz=text,
            text_ru=text,
            text_en=text,
            videos=tuple(videos),
        )


async def test_lesson_requires_video_and_active_listing_hides_empty(database) -> None:
    with pytest.raises(EmptyLessonError):
        await make_lesson(database)

    lesson = await make_lesson(database, video(1))
    async with database.session_factory.begin() as session:
        lesson_video = (await get_lesson_videos(session, lesson.id))[0]
        deleted, lesson_id = await delete_lesson_video(session, lesson_video.id)
    assert deleted and lesson_id == lesson.id

    async with database.session_factory() as session:
        stored = await get_lesson(session, lesson.id)
        page = await list_lessons(session, page=0, active_only=True)
    assert stored is not None and not stored.is_active
    assert page.items == ()

    async with database.session_factory.begin() as session:
        with pytest.raises(EmptyLessonError):
            await set_lesson_active(session, lesson.id, True)


async def test_multiple_videos_are_ordered_and_reorderable(database) -> None:
    lesson = await make_lesson(database, video(1), video(2), video(3))
    async with database.session_factory.begin() as session:
        items = await get_lesson_videos(session, lesson.id)
        assert [item.telegram_file_id for item in items] == ["file-1", "file-2", "file-3"]
        assert await move_lesson_video(session, items[2].id, -1)
    async with database.session_factory() as session:
        reordered = await get_lesson_videos(session, lesson.id)
    assert [item.telegram_file_id for item in reordered] == ["file-1", "file-3", "file-2"]


async def test_delivery_retries_shared_description_on_first_video_failure(database) -> None:
    lesson = await make_lesson(database, video(1), video(2), video(3))
    async with database.session_factory() as session:
        stored = await get_lesson(session, lesson.id)
        videos = await get_lesson_videos(session, lesson.id)
    assert stored is not None
    bot = AsyncMock()
    bot.send_video.side_effect = [
        TelegramBadRequest(method=SendVideo(chat_id=42, video="file-1"), message="failed"),
        None,
        None,
    ]

    report = await deliver_lesson(bot, 42, stored, videos, Language.RU)

    assert report.total == 3
    assert report.sent == 2
    assert report.failed == 1
    assert bot.send_video.await_args_list[0].kwargs["caption"] == "Цитрамон\n\nDescription"
    assert bot.send_video.await_args_list[1].kwargs["caption"] == "Цитрамон\n\nDescription"
    assert "caption" not in bot.send_video.await_args_list[2].kwargs
    assert all(call.kwargs["protect_content"] is True for call in bot.send_video.await_args_list)


async def test_long_shared_description_is_protected_and_sent_once(database) -> None:
    lesson = await make_lesson(database, video(1), video(2), text="x" * 4096)
    async with database.session_factory() as session:
        stored = await get_lesson(session, lesson.id)
        videos = await get_lesson_videos(session, lesson.id)
    assert isinstance(stored, VideoLesson)
    bot = AsyncMock()

    report = await deliver_lesson(bot, 42, stored, videos, Language.EN)

    assert report.sent == 2 and not report.description_failed
    assert len(bot.send_video.await_args_list[0].kwargs["caption"]) == 1024
    assert "caption" not in bot.send_video.await_args_list[1].kwargs
    assert bot.send_message.await_count == 1
    assert bot.send_message.await_args.kwargs["protect_content"] is True


async def test_description_overflow_failure_does_not_erase_video_success(database) -> None:
    lesson = await make_lesson(database, video(1), text="x" * 4096)
    async with database.session_factory() as session:
        stored = await get_lesson(session, lesson.id)
        videos = await get_lesson_videos(session, lesson.id)
    assert stored is not None
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramBadRequest(
        method=SendVideo(chat_id=42, video="file-1"), message="text failed"
    )

    report = await deliver_lesson(bot, 42, stored, videos, Language.EN)

    assert report.sent == 1
    assert report.failed == 0
    assert report.description_failed
