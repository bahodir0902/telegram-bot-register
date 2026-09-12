from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.albums import album_collector
from app.bot.callbacks import AdminCallback, AdminLessonCallback, LessonVideoCallback
from app.bot.filters.admin import AdminFilter, is_admin_user
from app.bot.keyboards.admin import (
    admin_menu_keyboard,
    lesson_delete_keyboard,
    lesson_detail_keyboard,
    lesson_draft_keyboard,
    lesson_list_keyboard,
    lesson_video_delete_keyboard,
    lesson_video_detail_keyboard,
    lesson_videos_keyboard,
    upload_cancel_keyboard,
)
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.bot.states.admin import (
    AdminLessonCreate,
    AdminLessonEdit,
    AdminLessonVideoAdd,
    AdminLessonVideoReplace,
)
from app.config import Settings
from app.db.models import VideoLesson
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr
from app.services.lessons import (
    EmptyLessonError,
    LessonVideoInput,
    add_lesson_video,
    create_lesson,
    delete_lesson,
    delete_lesson_video,
    deliver_lesson,
    get_lesson,
    get_lesson_video,
    get_lesson_videos,
    list_lesson_videos,
    list_lessons,
    localized_lesson_title,
    move_lesson,
    move_lesson_video,
    replace_lesson_video,
    set_lesson_active,
    update_lesson_field,
    validate_lesson_text,
    validate_lesson_title,
)

router = Router(name="admin_lessons")


def _preview(value: str, limit: int = 220) -> str:
    normalized = value.replace("\n", " ")
    return escape(normalized if len(normalized) <= limit else f"{normalized[: limit - 3]}...")


def lesson_detail_text(lesson: VideoLesson, video_count: int, language: Language) -> str:
    return tr(
        language,
        "lesson_admin_detail",
        title_uz=escape(lesson.title_uz),
        title_ru=escape(lesson.title_ru),
        title_en=escape(lesson.title_en),
        text_uz=_preview(lesson.text_uz),
        text_ru=_preview(lesson.text_ru),
        text_en=_preview(lesson.text_en),
        status=tr(language, "active" if lesson.is_active else "inactive"),
        count=video_count,
        order=lesson.sort_order,
    )


async def render_lesson_page(
    message: Message,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        result = await list_lessons(session, page=page, page_size=5)
    text = tr(
        language,
        "lessons_manage_title",
        total=result.total,
        page=result.page + 1,
        pages=result.pages,
    )
    if not result.items:
        text += f"\n\n{tr(language, 'lessons_manage_empty')}"
    await edit_text_safely(message, text, reply_markup=lesson_list_keyboard(result, language))


async def render_lesson_detail(
    message: Message,
    lesson_id: int,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        lesson = await get_lesson(session, lesson_id)
        videos = await get_lesson_videos(session, lesson_id) if lesson is not None else ()
    if lesson is None:
        await render_lesson_page(message, page, language, session_factory)
        return False
    await edit_text_safely(
        message,
        lesson_detail_text(lesson, len(videos), language),
        reply_markup=lesson_detail_keyboard(lesson, page, language),
    )
    return True


async def render_lesson_video_page(
    message: Message,
    lesson_id: int,
    page: int,
    lesson_page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        lesson = await get_lesson(session, lesson_id)
        result = (
            await list_lesson_videos(session, lesson_id=lesson_id, page=page)
            if lesson is not None
            else None
        )
    if lesson is None or result is None:
        await render_lesson_page(message, lesson_page, language, session_factory)
        return False
    text = tr(
        language,
        "lesson_videos_title",
        title=escape(localized_lesson_title(lesson, language)),
        total=result.total,
        page=result.page + 1,
        pages=result.pages,
    )
    if not result.items:
        text += f"\n\n{tr(language, 'lesson_videos_empty')}"
    await edit_text_safely(
        message,
        text,
        reply_markup=lesson_videos_keyboard(lesson, result, lesson_page, language),
    )
    return True


async def render_lesson_video_detail(
    message: Message,
    video_id: int,
    lesson_id: int,
    page: int,
    lesson_page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        video = await get_lesson_video(session, video_id)
    if video is None or video.lesson_id != lesson_id:
        await render_lesson_video_page(
            message, lesson_id, page, lesson_page, language, session_factory
        )
        return False
    await edit_text_safely(
        message,
        tr(
            language,
            "lesson_video_detail",
            filename=escape(video.original_filename or tr(language, "lesson_video_unnamed")),
            order=video.sort_order,
        ),
        reply_markup=lesson_video_detail_keyboard(video, page, lesson_page, language),
    )
    return True


def _video_input(message: Message) -> LessonVideoInput | None:
    if message.video is None:
        return None
    return LessonVideoInput(
        telegram_file_id=message.video.file_id,
        telegram_file_unique_id=message.video.file_unique_id,
        original_filename=(message.video.file_name or "")[:255] or None,
    )


@router.callback_query(AdminCallback.filter(F.action == "lessons"), AdminFilter())
async def manage_lessons(
    callback: CallbackQuery,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    if isinstance(callback.message, Message):
        await render_lesson_page(callback.message, 0, language, session_factory)


@router.callback_query(AdminLessonCallback.filter(F.action == "page"), AdminFilter())
async def change_lesson_page(
    callback: CallbackQuery,
    callback_data: AdminLessonCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_lesson_page(callback.message, callback_data.page, language, session_factory)


@router.callback_query(AdminLessonCallback.filter(F.action == "view"), AdminFilter())
async def view_lesson(
    callback: CallbackQuery,
    callback_data: AdminLessonCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_lesson_detail(
            callback.message,
            callback_data.lesson_id,
            callback_data.page,
            language,
            session_factory,
        )


@router.callback_query(AdminLessonCallback.filter(F.action == "add"), AdminFilter())
async def begin_lesson_create(
    callback: CallbackQuery, state: FSMContext, language: Language
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    await state.set_state(AdminLessonCreate.waiting_for_title_uz)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "lesson_title_uz_prompt"),
            reply_markup=upload_cancel_keyboard(language),
        )


_CREATE_STEPS = {
    AdminLessonCreate.waiting_for_title_uz.state: (
        "title_uz",
        AdminLessonCreate.waiting_for_title_ru,
        "lesson_title_ru_prompt",
        True,
    ),
    AdminLessonCreate.waiting_for_title_ru.state: (
        "title_ru",
        AdminLessonCreate.waiting_for_title_en,
        "lesson_title_en_prompt",
        True,
    ),
    AdminLessonCreate.waiting_for_title_en.state: (
        "title_en",
        AdminLessonCreate.waiting_for_text_uz,
        "lesson_text_uz_prompt",
        True,
    ),
    AdminLessonCreate.waiting_for_text_uz.state: (
        "text_uz",
        AdminLessonCreate.waiting_for_text_ru,
        "lesson_text_ru_prompt",
        False,
    ),
    AdminLessonCreate.waiting_for_text_ru.state: (
        "text_ru",
        AdminLessonCreate.waiting_for_text_en,
        "lesson_text_en_prompt",
        False,
    ),
    AdminLessonCreate.waiting_for_text_en.state: (
        "text_en",
        AdminLessonCreate.waiting_for_videos,
        "lesson_videos_prompt",
        False,
    ),
}


@router.message(
    AdminLessonCreate.waiting_for_title_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
@router.message(
    AdminLessonCreate.waiting_for_title_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
@router.message(
    AdminLessonCreate.waiting_for_title_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
@router.message(
    AdminLessonCreate.waiting_for_text_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
@router.message(
    AdminLessonCreate.waiting_for_text_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
@router.message(
    AdminLessonCreate.waiting_for_text_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_lesson_text_step(message: Message, state: FSMContext, language: Language) -> None:
    current = await state.get_state()
    step = _CREATE_STEPS.get(current or "")
    if step is None:
        await state.clear()
        await message.answer(tr(language, "lesson_edit_stale"))
        return
    field, next_state, prompt, is_title = step
    try:
        value = (
            validate_lesson_title(message.text) if is_title else validate_lesson_text(message.text)
        )
    except ValueError:
        await message.answer(
            tr(language, "lesson_title_invalid" if is_title else "lesson_text_invalid")
        )
        return
    await state.update_data(**{field: value})
    await state.set_state(next_state)
    await message.answer(
        tr(language, prompt),
        reply_markup=(
            lesson_draft_keyboard(language, can_save=False)
            if next_state == AdminLessonCreate.waiting_for_videos
            else upload_cancel_keyboard(language)
        ),
    )


@router.message(
    AdminLessonCreate.waiting_for_videos,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.video,
)
async def receive_lesson_draft_videos(
    message: Message, state: FSMContext, language: Language
) -> None:
    messages = await album_collector.collect(message)
    if messages is None:
        return
    new_items = [item for item in (_video_input(item) for item in messages) if item is not None]
    data = await state.get_data()
    raw_existing = data.get("videos")
    existing = list(raw_existing) if isinstance(raw_existing, list) else []
    known = {
        str(item.get("telegram_file_unique_id") or item.get("telegram_file_id"))
        for item in existing
        if isinstance(item, dict)
    }
    for item in new_items:
        identity = item.telegram_file_unique_id or item.telegram_file_id
        if identity not in known:
            existing.append(
                {
                    "telegram_file_id": item.telegram_file_id,
                    "telegram_file_unique_id": item.telegram_file_unique_id,
                    "original_filename": item.original_filename,
                }
            )
            known.add(identity)
    await state.update_data(videos=existing)
    await message.answer(
        tr(language, "lesson_videos_added", added=len(new_items), total=len(existing)),
        reply_markup=lesson_draft_keyboard(language, can_save=bool(existing)),
    )


@router.callback_query(AdminLessonCallback.filter(F.action == "create_save"), AdminFilter())
async def save_lesson_draft(
    callback: CallbackQuery,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    data = await state.get_data()
    raw_videos = data.get("videos")
    try:
        if not isinstance(raw_videos, list) or not raw_videos:
            raise ValueError("no videos")
        videos = tuple(
            LessonVideoInput(
                telegram_file_id=str(item["telegram_file_id"]),
                telegram_file_unique_id=(
                    str(item["telegram_file_unique_id"])
                    if item.get("telegram_file_unique_id") is not None
                    else None
                ),
                original_filename=(
                    str(item["original_filename"])
                    if item.get("original_filename") is not None
                    else None
                ),
            )
            for item in raw_videos
            if isinstance(item, dict)
        )
        async with session_factory.begin() as session:
            lesson = await create_lesson(
                session,
                title_uz=str(data["title_uz"]),
                title_ru=str(data["title_ru"]),
                title_en=str(data["title_en"]),
                text_uz=str(data["text_uz"]),
                text_ru=str(data["text_ru"]),
                text_en=str(data["text_en"]),
                videos=videos,
            )
    except KeyError, TypeError, ValueError:
        await answer_callback_safely(
            callback, tr(language, "lesson_draft_invalid"), show_alert=True
        )
        return
    await answer_callback_safely(callback, tr(language, "lesson_created"))
    await state.clear()
    if isinstance(callback.message, Message):
        await render_lesson_detail(callback.message, lesson.id, 0, language, session_factory)


@router.callback_query(
    AdminLessonCallback.filter(F.action.in_({"enable", "disable"})), AdminFilter()
)
async def toggle_lesson(
    callback: CallbackQuery,
    callback_data: AdminLessonCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        async with session_factory.begin() as session:
            changed = await set_lesson_active(
                session, callback_data.lesson_id, callback_data.action == "enable"
            )
    except EmptyLessonError:
        await answer_callback_safely(
            callback, tr(language, "lesson_empty_enable_forbidden"), show_alert=True
        )
        return
    if isinstance(callback.message, Message):
        await render_lesson_detail(
            callback.message,
            callback_data.lesson_id,
            callback_data.page,
            language,
            session_factory,
        )
    await answer_callback_safely(
        callback,
        tr(language, "lesson_enabled" if callback_data.action == "enable" else "lesson_disabled")
        if changed
        else tr(language, "lesson_missing"),
        show_alert=not changed,
    )


@router.callback_query(AdminLessonCallback.filter(F.action.in_({"up", "down"})), AdminFilter())
async def reorder_lesson(
    callback: CallbackQuery,
    callback_data: AdminLessonCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        moved = await move_lesson(
            session, callback_data.lesson_id, -1 if callback_data.action == "up" else 1
        )
    if isinstance(callback.message, Message):
        await render_lesson_detail(
            callback.message,
            callback_data.lesson_id,
            callback_data.page,
            language,
            session_factory,
        )
    await answer_callback_safely(
        callback, tr(language, "option_reordered" if moved else "option_order_boundary")
    )


@router.callback_query(
    AdminLessonCallback.filter(F.action.startswith("title_") | F.action.startswith("text_")),
    AdminFilter(),
)
async def begin_lesson_edit(
    callback: CallbackQuery,
    callback_data: AdminLessonCallback,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    field = callback_data.action
    async with session_factory() as session:
        lesson = await get_lesson(session, callback_data.lesson_id)
    if lesson is None:
        await answer_callback_safely(callback, tr(language, "lesson_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    await state.clear()
    await state.update_data(lesson_id=lesson.id, page=callback_data.page, field=field)
    await state.set_state(AdminLessonEdit.waiting_for_value)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "lesson_field_edit_prompt", field=field.upper()),
            reply_markup=upload_cancel_keyboard(language),
        )


@router.message(
    AdminLessonEdit.waiting_for_value,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_lesson_edit(
    message: Message,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    data = await state.get_data()
    try:
        lesson_id = int(data["lesson_id"])
        page = int(data["page"])
        field = str(data["field"])
        async with session_factory.begin() as session:
            lesson = await update_lesson_field(session, lesson_id, field, message.text or "")
    except KeyError, TypeError, ValueError:
        await message.answer(tr(language, "lesson_field_invalid"))
        return
    await state.clear()
    if lesson is None:
        await message.answer(
            tr(language, "lesson_missing"), reply_markup=admin_menu_keyboard(language)
        )
        return
    await message.answer(
        tr(language, "lesson_updated"),
        reply_markup=lesson_detail_keyboard(lesson, page, language),
    )


@router.callback_query(AdminLessonCallback.filter(F.action == "videos"), AdminFilter())
async def manage_lesson_videos(
    callback: CallbackQuery,
    callback_data: AdminLessonCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_lesson_video_page(
            callback.message,
            callback_data.lesson_id,
            0,
            callback_data.page,
            language,
            session_factory,
        )


@router.callback_query(LessonVideoCallback.filter(F.action == "page"), AdminFilter())
async def change_lesson_video_page(
    callback: CallbackQuery,
    callback_data: LessonVideoCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_lesson_video_page(
            callback.message,
            callback_data.lesson_id,
            callback_data.page,
            callback_data.lesson_page,
            language,
            session_factory,
        )


@router.callback_query(LessonVideoCallback.filter(F.action == "view"), AdminFilter())
async def view_lesson_video(
    callback: CallbackQuery,
    callback_data: LessonVideoCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_lesson_video_detail(
            callback.message,
            callback_data.video_id,
            callback_data.lesson_id,
            callback_data.page,
            callback_data.lesson_page,
            language,
            session_factory,
        )


@router.callback_query(LessonVideoCallback.filter(F.action == "add"), AdminFilter())
async def begin_lesson_video_add(
    callback: CallbackQuery,
    callback_data: LessonVideoCallback,
    state: FSMContext,
    language: Language,
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    await state.update_data(
        lesson_id=callback_data.lesson_id,
        page=callback_data.page,
        lesson_page=callback_data.lesson_page,
    )
    await state.set_state(AdminLessonVideoAdd.waiting_for_videos)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "lesson_video_add_prompt"),
            reply_markup=upload_cancel_keyboard(language),
        )


@router.message(
    AdminLessonVideoAdd.waiting_for_videos,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.video,
)
async def receive_lesson_video_add(
    message: Message,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    messages = await album_collector.collect(message)
    if messages is None:
        return
    inputs = tuple(item for item in (_video_input(msg) for msg in messages) if item is not None)
    data = await state.get_data()
    try:
        lesson_id = int(data["lesson_id"])
        page = int(data["page"])
        lesson_page = int(data["lesson_page"])
    except KeyError, TypeError, ValueError:
        await state.clear()
        await message.answer(tr(language, "lesson_edit_stale"))
        return
    async with session_factory.begin() as session:
        saved = [await add_lesson_video(session, lesson_id, item) for item in inputs]
    await state.clear()
    if not inputs or any(item is None for item in saved):
        await message.answer(
            tr(language, "lesson_missing"), reply_markup=admin_menu_keyboard(language)
        )
        return
    await message.answer(tr(language, "lesson_videos_saved", count=len(saved)))
    await render_lesson_video_page(message, lesson_id, page, lesson_page, language, session_factory)


@router.callback_query(LessonVideoCallback.filter(F.action == "replace"), AdminFilter())
async def begin_lesson_video_replace(
    callback: CallbackQuery,
    callback_data: LessonVideoCallback,
    state: FSMContext,
    language: Language,
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    await state.update_data(
        video_id=callback_data.video_id,
        lesson_id=callback_data.lesson_id,
        page=callback_data.page,
        lesson_page=callback_data.lesson_page,
    )
    await state.set_state(AdminLessonVideoReplace.waiting_for_video)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "lesson_video_replace_prompt"),
            reply_markup=upload_cancel_keyboard(language),
        )


@router.message(
    AdminLessonVideoReplace.waiting_for_video,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.video,
)
async def receive_lesson_video_replace(
    message: Message,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    messages = await album_collector.collect(message)
    if messages is None:
        return
    if len(messages) != 1:
        await message.answer(tr(language, "lesson_replace_one_video"))
        return
    video_input = _video_input(messages[0])
    data = await state.get_data()
    try:
        video_id = int(data["video_id"])
        lesson_id = int(data["lesson_id"])
        page = int(data["page"])
        lesson_page = int(data["lesson_page"])
    except KeyError, TypeError, ValueError:
        await state.clear()
        await message.answer(tr(language, "lesson_edit_stale"))
        return
    async with session_factory.begin() as session:
        existing = await get_lesson_video(session, video_id)
        video = (
            await replace_lesson_video(session, video_id, video_input)
            if existing is not None and existing.lesson_id == lesson_id and video_input is not None
            else None
        )
    await state.clear()
    if video is None:
        await message.answer(tr(language, "lesson_video_missing"))
        return
    await message.answer(
        tr(language, "lesson_video_replaced"),
        reply_markup=lesson_video_detail_keyboard(video, page, lesson_page, language),
    )


@router.callback_query(LessonVideoCallback.filter(F.action.in_({"up", "down"})), AdminFilter())
async def reorder_lesson_video(
    callback: CallbackQuery,
    callback_data: LessonVideoCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        video = await get_lesson_video(session, callback_data.video_id)
        moved = (
            await move_lesson_video(
                session,
                callback_data.video_id,
                -1 if callback_data.action == "up" else 1,
            )
            if video is not None and video.lesson_id == callback_data.lesson_id
            else False
        )
    if isinstance(callback.message, Message):
        await render_lesson_video_detail(
            callback.message,
            callback_data.video_id,
            callback_data.lesson_id,
            callback_data.page,
            callback_data.lesson_page,
            language,
            session_factory,
        )
    await answer_callback_safely(
        callback, tr(language, "option_reordered" if moved else "option_order_boundary")
    )


@router.callback_query(AdminLessonCallback.filter(F.action == "preview"), AdminFilter())
async def preview_lesson(
    callback: CallbackQuery,
    callback_data: AdminLessonCallback,
    bot: Bot,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        lesson = await get_lesson(session, callback_data.lesson_id)
        videos = await get_lesson_videos(session, callback_data.lesson_id)
    if lesson is None or not videos:
        await answer_callback_safely(callback, tr(language, "lesson_missing"), show_alert=True)
        return
    report = await deliver_lesson(bot, callback.from_user.id, lesson, videos, language)
    await answer_callback_safely(
        callback,
        tr(language, "lesson_preview_sent", sent=report.sent, total=report.total),
        show_alert=bool(report.failed or report.description_failed),
    )


@router.callback_query(AdminLessonCallback.filter(F.action == "delete_request"), AdminFilter())
async def request_lesson_delete(
    callback: CallbackQuery,
    callback_data: AdminLessonCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        lesson = await get_lesson(session, callback_data.lesson_id)
    if lesson is None:
        await answer_callback_safely(callback, tr(language, "lesson_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(
                language,
                "lesson_delete_prompt",
                title=escape(localized_lesson_title(lesson, language)),
            ),
            reply_markup=lesson_delete_keyboard(lesson, callback_data.page, language),
        )


@router.callback_query(AdminLessonCallback.filter(F.action == "delete_confirm"), AdminFilter())
async def confirm_lesson_delete(
    callback: CallbackQuery,
    callback_data: AdminLessonCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        deleted = await delete_lesson(session, callback_data.lesson_id)
    if isinstance(callback.message, Message):
        await render_lesson_page(callback.message, callback_data.page, language, session_factory)
    await answer_callback_safely(
        callback,
        tr(language, "lesson_deleted" if deleted else "lesson_already_deleted"),
        show_alert=not deleted,
    )


@router.callback_query(LessonVideoCallback.filter(F.action == "delete_request"), AdminFilter())
async def request_lesson_video_delete(
    callback: CallbackQuery,
    callback_data: LessonVideoCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        video = await get_lesson_video(session, callback_data.video_id)
    if video is None or video.lesson_id != callback_data.lesson_id:
        await answer_callback_safely(
            callback, tr(language, "lesson_video_missing"), show_alert=True
        )
        return
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "lesson_video_delete_prompt"),
            reply_markup=lesson_video_delete_keyboard(
                video, callback_data.page, callback_data.lesson_page, language
            ),
        )


@router.callback_query(LessonVideoCallback.filter(F.action == "delete_confirm"), AdminFilter())
async def confirm_lesson_video_delete(
    callback: CallbackQuery,
    callback_data: LessonVideoCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        video = await get_lesson_video(session, callback_data.video_id)
        deleted, _ = (
            await delete_lesson_video(session, callback_data.video_id)
            if video is not None and video.lesson_id == callback_data.lesson_id
            else (False, None)
        )
    if isinstance(callback.message, Message):
        await render_lesson_video_page(
            callback.message,
            callback_data.lesson_id,
            callback_data.page,
            callback_data.lesson_page,
            language,
            session_factory,
        )
    await answer_callback_safely(
        callback,
        tr(language, "lesson_video_deleted" if deleted else "lesson_video_missing"),
        show_alert=not deleted,
    )


@router.message(
    AdminLessonCreate.waiting_for_videos,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminLessonVideoAdd.waiting_for_videos,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminLessonVideoReplace.waiting_for_video,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
async def reject_non_video(message: Message, language: Language) -> None:
    await message.answer(tr(language, "lesson_video_required"))


@router.callback_query(AdminLessonCallback.filter())
@router.callback_query(LessonVideoCallback.filter())
async def reject_lesson_admin_callback(
    callback: CallbackQuery, settings: Settings, language: Language
) -> None:
    sender_id = callback.from_user.id if callback.from_user else None
    await answer_callback_safely(
        callback,
        tr(
            language,
            "admin_callback_stale"
            if is_admin_user(sender_id, settings.admin_ids)
            else "admin_action_unauthorized",
        ),
        show_alert=True,
    )
