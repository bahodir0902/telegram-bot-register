from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MediaType, VideoLesson, VideoLessonVideo
from app.i18n import DEFAULT_LANGUAGE, Language
from app.services.content import TELEGRAM_CAPTION_LIMIT, send_content, validate_content_text

logger = logging.getLogger(__name__)
LESSON_TITLE_LIMIT = 64


class EmptyLessonError(ValueError):
    """A lesson without videos cannot be exposed to users."""


@dataclass(frozen=True, slots=True)
class LessonVideoInput:
    telegram_file_id: str
    telegram_file_unique_id: str | None
    original_filename: str | None


@dataclass(frozen=True, slots=True)
class LessonPage:
    items: tuple[VideoLesson, ...]
    page: int
    pages: int
    total: int


@dataclass(frozen=True, slots=True)
class LessonVideoPage:
    items: tuple[VideoLessonVideo, ...]
    page: int
    pages: int
    total: int


@dataclass(frozen=True, slots=True)
class LessonDeliveryReport:
    total: int
    sent: int
    failed: int
    description_failed: bool = False


def validate_lesson_title(value: str | None) -> str:
    if value is None or not value.strip():
        raise ValueError("lesson title cannot be empty")
    normalized = value.strip()
    if len(normalized) > LESSON_TITLE_LIMIT:
        raise ValueError(f"lesson title exceeds {LESSON_TITLE_LIMIT} characters")
    return normalized


def validate_lesson_text(value: str | None) -> str:
    return validate_content_text(value, MediaType.VIDEO)


def localized_lesson_title(lesson: VideoLesson, language: Language | str | None) -> str:
    try:
        resolved = Language(language) if language is not None else DEFAULT_LANGUAGE
    except ValueError:
        resolved = DEFAULT_LANGUAGE
    return {
        Language.UZ: lesson.title_uz,
        Language.RU: lesson.title_ru,
        Language.EN: lesson.title_en,
    }[resolved]


def localized_lesson_text(lesson: VideoLesson, language: Language | str | None) -> str:
    try:
        resolved = Language(language) if language is not None else DEFAULT_LANGUAGE
    except ValueError:
        resolved = DEFAULT_LANGUAGE
    return {
        Language.UZ: lesson.text_uz,
        Language.RU: lesson.text_ru,
        Language.EN: lesson.text_en,
    }[resolved]


async def create_lesson(
    session: AsyncSession,
    *,
    title_uz: str,
    title_ru: str,
    title_en: str,
    text_uz: str,
    text_ru: str,
    text_en: str,
    videos: tuple[LessonVideoInput, ...],
) -> VideoLesson:
    if not videos:
        raise EmptyLessonError("a lesson requires at least one video")
    highest_order = await session.scalar(select(func.max(VideoLesson.sort_order)))
    lesson = VideoLesson(
        title_uz=validate_lesson_title(title_uz),
        title_ru=validate_lesson_title(title_ru),
        title_en=validate_lesson_title(title_en),
        text_uz=validate_lesson_text(text_uz),
        text_ru=validate_lesson_text(text_ru),
        text_en=validate_lesson_text(text_en),
        is_active=True,
        sort_order=(highest_order or 0) + 10,
    )
    session.add(lesson)
    await session.flush()
    for video in videos:
        await add_lesson_video(session, lesson.id, video)
    return lesson


async def get_lesson(session: AsyncSession, lesson_id: int) -> VideoLesson | None:
    return await session.get(VideoLesson, lesson_id)


async def get_lesson_video(session: AsyncSession, video_id: int) -> VideoLessonVideo | None:
    return await session.get(VideoLessonVideo, video_id)


async def get_lesson_videos(session: AsyncSession, lesson_id: int) -> tuple[VideoLessonVideo, ...]:
    result = await session.scalars(
        select(VideoLessonVideo)
        .where(VideoLessonVideo.lesson_id == lesson_id)
        .order_by(VideoLessonVideo.sort_order.asc(), VideoLessonVideo.id.asc())
    )
    return tuple(result.all())


async def list_lessons(
    session: AsyncSession, *, page: int, page_size: int = 8, active_only: bool = False
) -> LessonPage:
    count_query = select(func.count(VideoLesson.id))
    query = select(VideoLesson)
    if active_only:
        video_exists = (
            select(VideoLessonVideo.id).where(VideoLessonVideo.lesson_id == VideoLesson.id).exists()
        )
        count_query = count_query.where(VideoLesson.is_active.is_(True), video_exists)
        query = query.where(VideoLesson.is_active.is_(True), video_exists)
    total = int(await session.scalar(count_query) or 0)
    pages = max(1, math.ceil(total / page_size))
    normalized_page = min(max(page, 0), pages - 1)
    result = await session.scalars(
        query.order_by(VideoLesson.sort_order.asc(), VideoLesson.id.asc())
        .offset(normalized_page * page_size)
        .limit(page_size)
    )
    return LessonPage(tuple(result.all()), normalized_page, pages, total)


async def list_lesson_videos(
    session: AsyncSession, *, lesson_id: int, page: int, page_size: int = 8
) -> LessonVideoPage:
    total = int(
        await session.scalar(
            select(func.count(VideoLessonVideo.id)).where(VideoLessonVideo.lesson_id == lesson_id)
        )
        or 0
    )
    pages = max(1, math.ceil(total / page_size))
    normalized_page = min(max(page, 0), pages - 1)
    result = await session.scalars(
        select(VideoLessonVideo)
        .where(VideoLessonVideo.lesson_id == lesson_id)
        .order_by(VideoLessonVideo.sort_order.asc(), VideoLessonVideo.id.asc())
        .offset(normalized_page * page_size)
        .limit(page_size)
    )
    return LessonVideoPage(tuple(result.all()), normalized_page, pages, total)


async def update_lesson_field(
    session: AsyncSession, lesson_id: int, field: str, value: str
) -> VideoLesson | None:
    lesson = await get_lesson(session, lesson_id)
    if lesson is None or field not in {
        "title_uz",
        "title_ru",
        "title_en",
        "text_uz",
        "text_ru",
        "text_en",
    }:
        return None
    normalized = (
        validate_lesson_title(value) if field.startswith("title_") else validate_lesson_text(value)
    )
    setattr(lesson, field, normalized)
    return lesson


async def set_lesson_active(session: AsyncSession, lesson_id: int, active: bool) -> bool:
    if await get_lesson(session, lesson_id) is None:
        return False
    if active:
        count = int(
            await session.scalar(
                select(func.count(VideoLessonVideo.id)).where(
                    VideoLessonVideo.lesson_id == lesson_id
                )
            )
            or 0
        )
        if not count:
            raise EmptyLessonError("an empty lesson cannot be activated")
    result = await session.execute(
        update(VideoLesson).where(VideoLesson.id == lesson_id).values(is_active=active)
    )
    return result.rowcount == 1


async def delete_lesson(session: AsyncSession, lesson_id: int) -> bool:
    result = await session.execute(delete(VideoLesson).where(VideoLesson.id == lesson_id))
    return result.rowcount == 1


async def add_lesson_video(
    session: AsyncSession, lesson_id: int, video_input: LessonVideoInput
) -> VideoLessonVideo | None:
    if await get_lesson(session, lesson_id) is None or not video_input.telegram_file_id:
        return None
    highest_order = await session.scalar(
        select(func.max(VideoLessonVideo.sort_order)).where(VideoLessonVideo.lesson_id == lesson_id)
    )
    video = VideoLessonVideo(
        lesson_id=lesson_id,
        telegram_file_id=video_input.telegram_file_id,
        telegram_file_unique_id=video_input.telegram_file_unique_id,
        original_filename=video_input.original_filename,
        sort_order=(highest_order or 0) + 10,
    )
    session.add(video)
    await session.flush()
    return video


async def replace_lesson_video(
    session: AsyncSession, video_id: int, video_input: LessonVideoInput
) -> VideoLessonVideo | None:
    video = await get_lesson_video(session, video_id)
    if video is None or not video_input.telegram_file_id:
        return None
    video.telegram_file_id = video_input.telegram_file_id
    video.telegram_file_unique_id = video_input.telegram_file_unique_id
    video.original_filename = video_input.original_filename
    return video


async def delete_lesson_video(session: AsyncSession, video_id: int) -> tuple[bool, int | None]:
    video = await get_lesson_video(session, video_id)
    if video is None:
        return False, None
    lesson_id = video.lesson_id
    await session.delete(video)
    await session.flush()
    remaining = int(
        await session.scalar(
            select(func.count(VideoLessonVideo.id)).where(VideoLessonVideo.lesson_id == lesson_id)
        )
        or 0
    )
    if not remaining:
        await session.execute(
            update(VideoLesson).where(VideoLesson.id == lesson_id).values(is_active=False)
        )
    return True, lesson_id


async def _move_ordered(
    session: AsyncSession,
    *,
    model: type[VideoLesson] | type[VideoLessonVideo],
    object_id: int,
    direction: int,
    lesson_id: int | None = None,
) -> bool:
    if direction not in {-1, 1}:
        return False
    query = select(model)
    if lesson_id is not None:
        query = query.where(VideoLessonVideo.lesson_id == lesson_id)
    ordered = list(
        (await session.scalars(query.order_by(model.sort_order.asc(), model.id.asc()))).all()
    )
    try:
        current_index = next(index for index, item in enumerate(ordered) if item.id == object_id)
    except StopIteration:
        return False
    target_index = current_index + direction
    if target_index < 0 or target_index >= len(ordered):
        return False
    ordered[current_index], ordered[target_index] = ordered[target_index], ordered[current_index]
    for index, item in enumerate(ordered, start=1):
        item.sort_order = index * 10
    await session.flush()
    return True


async def move_lesson(session: AsyncSession, lesson_id: int, direction: int) -> bool:
    return await _move_ordered(session, model=VideoLesson, object_id=lesson_id, direction=direction)


async def move_lesson_video(session: AsyncSession, video_id: int, direction: int) -> bool:
    video = await get_lesson_video(session, video_id)
    if video is None:
        return False
    return await _move_ordered(
        session,
        model=VideoLessonVideo,
        object_id=video_id,
        direction=direction,
        lesson_id=video.lesson_id,
    )


async def deliver_lesson(
    bot: Bot,
    user_id: int,
    lesson: VideoLesson,
    videos: tuple[VideoLessonVideo, ...],
    language: Language,
) -> LessonDeliveryReport:
    sent = 0
    failed = 0
    description_failed = False
    description_pending = True
    description = (
        f"{localized_lesson_title(lesson, language)}\n\n{localized_lesson_text(lesson, language)}"
    )
    for video in videos:
        try:
            if description_pending:
                await bot.send_video(
                    user_id,
                    video.telegram_file_id,
                    caption=escape(description[:TELEGRAM_CAPTION_LIMIT]),
                    protect_content=True,
                )
            else:
                await bot.send_video(user_id, video.telegram_file_id, protect_content=True)
            sent += 1
        except TelegramAPIError:
            failed += 1
            logger.exception(
                "Failed to deliver lesson video",
                extra={"lesson_id": lesson.id, "video_id": video.id, "user_id": user_id},
            )
            continue
        if description_pending:
            description_pending = False
            remaining = description[TELEGRAM_CAPTION_LIMIT:]
            if remaining:
                try:
                    await send_content(
                        bot,
                        user_id,
                        media_type=MediaType.TEXT,
                        telegram_file_id="",
                        text=remaining,
                        protect_content=True,
                    )
                except TelegramAPIError:
                    description_failed = True
                    logger.exception(
                        "Failed to deliver lesson description overflow",
                        extra={"lesson_id": lesson.id, "user_id": user_id},
                    )
    return LessonDeliveryReport(
        total=len(videos),
        sent=sent,
        failed=failed,
        description_failed=description_failed,
    )
