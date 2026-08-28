from __future__ import annotations

from html import escape
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.albums import album_collector
from app.bot.callbacks import (
    AdminCallback,
    BroadcastCallback,
    ChannelCallback,
)
from app.bot.content_input import content_validation_text, extract_content
from app.bot.filters.admin import AdminFilter, is_admin_user
from app.bot.keyboards.admin import (
    admin_menu_keyboard,
    broadcast_preview_keyboard,
    broadcast_status_keyboard,
    channel_delete_keyboard,
    channel_detail_keyboard,
    channel_list_keyboard,
    upload_cancel_keyboard,
)
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.bot.states.admin import (
    AdminBroadcast,
    AdminChannelAdd,
    AdminChannelEdit,
)
from app.config import Settings
from app.db.models import Channel, MediaType
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr
from app.services.broadcasts import (
    BroadcastProgress,
    BroadcastWorker,
    cancel_broadcast,
    create_broadcast,
    get_broadcast_progress,
)
from app.services.channels import (
    ChannelAlreadyExistsError,
    ChannelValidationError,
    ChannelValidationKind,
    LastChannelDeletionError,
    add_channel,
    delete_channel,
    get_channel,
    get_channel_by_chat_id,
    list_channels,
    update_channel_identity,
    update_channel_url,
    validate_telegram_channel,
)
from app.services.content import send_content, validate_content_text
from app.validation import validate_channel_url

router = Router(name="admin")


def channel_detail_text(channel: Channel, language: Language) -> str:
    return tr(
        language,
        "channel_detail",
        title=escape(channel.title),
        chat_id=escape(channel.telegram_chat_id),
        url=escape(channel.join_url),
    )


def channel_validation_text(error: ChannelValidationError, language: Language) -> str:
    keys = {
        ChannelValidationKind.INVALID_ID: "channel_invalid_id",
        ChannelValidationKind.LOOKUP_FAILED: "channel_lookup_failed",
        ChannelValidationKind.NOT_CHANNEL: "channel_not_channel",
        ChannelValidationKind.BOT_NOT_ADMIN: "channel_bot_not_admin",
    }
    return tr(language, keys[error.kind])


def broadcast_progress_text(progress: BroadcastProgress, language: Language) -> str:
    status = tr(language, f"broadcast_status_{progress.broadcast.status.value}")
    return tr(
        language,
        "broadcast_status",
        status=status,
        total=progress.total,
        sent=progress.sent,
        pending=progress.pending + progress.sending,
        failed=progress.failed,
        cancelled=progress.cancelled,
    )


async def render_broadcast_progress(
    message: Message,
    broadcast_id: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        progress = await get_broadcast_progress(session, broadcast_id)
    if progress is None:
        return False
    await edit_text_safely(
        message,
        broadcast_progress_text(progress, language),
        reply_markup=broadcast_status_keyboard(
            progress.broadcast.id, progress.broadcast.status, language
        ),
    )
    return True


async def render_channel_page(
    message: Message,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        result = await list_channels(session, page=page)
    text = tr(
        language,
        "channels_title",
        total=result.total,
        page=result.page + 1,
        pages=result.pages,
    )
    if not result.items:
        text += f"\n\n{tr(language, 'channels_empty')}"
    await edit_text_safely(
        message,
        text,
        reply_markup=channel_list_keyboard(result, language),
    )


async def render_channel_detail(
    message: Message,
    channel_id: int,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        channel = await get_channel(session, channel_id)
    if channel is None:
        await render_channel_page(message, page, language, session_factory)
        return False
    await edit_text_safely(
        message,
        channel_detail_text(channel, language),
        reply_markup=channel_detail_keyboard(channel, page, language),
    )
    return True


@router.message(Command("admin"), F.chat.type == ChatType.PRIVATE, AdminFilter())
async def admin_menu(message: Message, state: FSMContext, language: Language) -> None:
    await state.clear()
    await message.answer(
        tr(language, "admin_menu"),
        reply_markup=admin_menu_keyboard(language),
    )


@router.message(Command("admin"))
async def reject_admin_command(message: Message, settings: Settings, language: Language) -> None:
    sender_id = message.from_user.id if message.from_user else None
    text = (
        tr(language, "admin_unauthorized")
        if not is_admin_user(sender_id, settings.admin_ids)
        else tr(language, "admin_private_only")
    )
    await message.answer(text)


@router.callback_query(AdminCallback.filter(F.action == "menu"), AdminFilter())
async def return_to_admin_menu(
    callback: CallbackQuery, state: FSMContext, language: Language
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "admin_menu"),
            reply_markup=admin_menu_keyboard(language),
        )


@router.callback_query(AdminCallback.filter(F.action == "broadcast"), AdminFilter())
async def begin_broadcast(callback: CallbackQuery, state: FSMContext, language: Language) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    await state.update_data(purpose="broadcast", request_token=uuid4().hex)
    await state.set_state(AdminBroadcast.waiting_for_content)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "broadcast_content_prompt"),
            reply_markup=upload_cancel_keyboard(language),
        )


@router.message(
    AdminBroadcast.waiting_for_content,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.video | F.photo | F.document | (F.text & ~F.text.startswith("/")),
)
async def receive_admin_content(
    message: Message,
    state: FSMContext,
    language: Language,
) -> None:
    messages = await album_collector.collect(message)
    if messages is None:
        return
    if len(messages) > 1:
        await message.answer(
            tr(language, "broadcast_album_unsupported"),
            reply_markup=upload_cancel_keyboard(language),
        )
        return
    message = messages[0]
    extracted = extract_content(message)
    if extracted is None:
        return
    payload, initial_uz = extracted
    media_type = MediaType(str(payload["media_type"]))
    error_text = (
        content_validation_text(initial_uz, media_type, language)
        if initial_uz is not None
        else None
    )
    if error_text is not None:
        await message.answer(error_text, reply_markup=upload_cancel_keyboard(language))
        return

    await state.update_data(**payload)
    if initial_uz is None:
        await state.set_state(AdminBroadcast.waiting_for_uz)
        prompt_key = "content_uz_prompt"
    else:
        await state.update_data(text_uz=initial_uz)
        await state.set_state(AdminBroadcast.waiting_for_ru)
        prompt_key = "content_ru_prompt"
    await message.answer(tr(language, prompt_key), reply_markup=upload_cancel_keyboard(language))


@router.message(
    AdminBroadcast.waiting_for_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_uz_content(message: Message, state: FSMContext, language: Language) -> None:
    data = await state.get_data()
    media_type = MediaType(str(data["media_type"]))
    error_text = content_validation_text(message.text, media_type, language)
    if error_text is not None:
        await message.answer(error_text)
        return
    await state.update_data(text_uz=message.text)
    await state.set_state(AdminBroadcast.waiting_for_ru)
    await message.answer(
        tr(language, "content_ru_prompt"),
        reply_markup=upload_cancel_keyboard(language),
    )


@router.message(
    AdminBroadcast.waiting_for_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_ru_content(message: Message, state: FSMContext, language: Language) -> None:
    data = await state.get_data()
    media_type = MediaType(str(data["media_type"]))
    error_text = content_validation_text(message.text, media_type, language)
    if error_text is not None:
        await message.answer(error_text)
        return
    await state.update_data(text_ru=message.text)
    await state.set_state(AdminBroadcast.waiting_for_en)
    await message.answer(
        tr(language, "content_en_prompt"),
        reply_markup=upload_cancel_keyboard(language),
    )


@router.message(
    AdminBroadcast.waiting_for_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_en_content(
    message: Message,
    bot: Bot,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    data = await state.get_data()
    media_type = MediaType(str(data["media_type"]))
    error_text = content_validation_text(message.text, media_type, language)
    if error_text is not None:
        await message.answer(error_text)
        return
    await state.update_data(text_en=message.text)
    data["text_en"] = message.text
    preview_text = {
        Language.UZ: str(data["text_uz"]),
        Language.RU: str(data["text_ru"]),
        Language.EN: message.text,
    }[language]
    try:
        await message.answer(tr(language, "broadcast_preview"))
        await send_content(
            bot,
            message.chat.id,
            media_type=media_type,
            telegram_file_id=str(data.get("telegram_file_id") or ""),
            text=preview_text,
            reply_markup=broadcast_preview_keyboard(language),
        )
    except TelegramAPIError:
        await state.clear()
        await message.answer(
            tr(language, "broadcast_preview_failed"),
            reply_markup=admin_menu_keyboard(language),
        )
        return
    await state.set_state(AdminBroadcast.waiting_for_confirmation)


@router.message(
    AdminBroadcast.waiting_for_content,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminBroadcast.waiting_for_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminBroadcast.waiting_for_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminBroadcast.waiting_for_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
async def reject_unsupported_content(message: Message, language: Language) -> None:
    await message.answer(
        tr(language, "content_unsupported"),
        reply_markup=upload_cancel_keyboard(language),
    )


@router.message(Command("cancel"), F.chat.type == ChatType.PRIVATE, AdminFilter())
async def cancel_admin_state(message: Message, state: FSMContext, language: Language) -> None:
    await state.clear()
    await message.answer(
        tr(language, "admin_menu"),
        reply_markup=admin_menu_keyboard(language),
    )


@router.callback_query(BroadcastCallback.filter(F.action == "cancel_draft"), AdminFilter())
async def cancel_broadcast_draft(
    callback: CallbackQuery, state: FSMContext, language: Language
) -> None:
    await answer_callback_safely(callback, tr(language, "broadcast_draft_cancelled"))
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            tr(language, "admin_menu"),
            reply_markup=admin_menu_keyboard(language),
        )


@router.callback_query(BroadcastCallback.filter(F.action == "confirm"), AdminFilter())
async def confirm_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
    broadcast_worker: BroadcastWorker,
) -> None:
    await answer_callback_safely(callback)
    sender = callback.from_user
    message = callback.message
    current_state = await state.get_state()
    if (
        sender is None
        or not isinstance(message, Message)
        or current_state != AdminBroadcast.waiting_for_confirmation.state
    ):
        if isinstance(message, Message):
            await message.answer(tr(language, "broadcast_confirm_stale"))
        return

    data = await state.get_data()
    try:
        media_type = MediaType(str(data["media_type"]))
        text_uz = validate_content_text(str(data["text_uz"]), media_type)
        text_ru = validate_content_text(str(data["text_ru"]), media_type)
        text_en = validate_content_text(str(data["text_en"]), media_type)
        request_token = str(data["request_token"])
    except KeyError, ValueError:
        await state.clear()
        await message.answer(
            tr(language, "broadcast_confirm_stale"),
            reply_markup=admin_menu_keyboard(language),
        )
        return

    async with session_factory.begin() as session:
        broadcast, _created = await create_broadcast(
            session,
            request_token=request_token,
            admin_telegram_id=sender.id,
            admin_language=language,
            media_type=media_type,
            telegram_file_id=str(data.get("telegram_file_id") or ""),
            telegram_file_unique_id=data.get("telegram_file_unique_id"),
            original_filename=data.get("original_filename"),
            text_uz=text_uz,
            text_ru=text_ru,
            text_en=text_en,
        )
    await state.clear()
    broadcast_worker.wake()
    async with session_factory() as session:
        progress = await get_broadcast_progress(session, broadcast.id)
    if progress is None:  # pragma: no cover - defensive database boundary
        await message.answer(tr(language, "broadcast_missing"))
        return
    await message.answer(
        f"{tr(language, 'broadcast_queued')}\n\n{broadcast_progress_text(progress, language)}",
        reply_markup=broadcast_status_keyboard(
            progress.broadcast.id, progress.broadcast.status, language
        ),
    )


@router.callback_query(BroadcastCallback.filter(F.action == "status"), AdminFilter())
async def refresh_broadcast_status(
    callback: CallbackQuery,
    callback_data: BroadcastCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    if not isinstance(callback.message, Message):
        await answer_callback_safely(callback)
        return
    found = await render_broadcast_progress(
        callback.message,
        callback_data.broadcast_id,
        language,
        session_factory,
    )
    await answer_callback_safely(
        callback,
        None if found else tr(language, "broadcast_missing"),
        show_alert=not found,
    )


@router.callback_query(BroadcastCallback.filter(F.action == "cancel"), AdminFilter())
async def cancel_pending_broadcast(
    callback: CallbackQuery,
    callback_data: BroadcastCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
    broadcast_worker: BroadcastWorker,
) -> None:
    async with session_factory.begin() as session:
        changed = await cancel_broadcast(session, callback_data.broadcast_id)
        progress = await get_broadcast_progress(session, callback_data.broadcast_id)
    if progress is None:
        await answer_callback_safely(callback, tr(language, "broadcast_missing"), show_alert=True)
        return
    broadcast_worker.wake()
    await answer_callback_safely(
        callback,
        tr(
            language,
            "broadcast_cancelled_pending" if changed else "broadcast_already_finished",
        ),
        show_alert=not changed,
    )
    if isinstance(callback.message, Message):
        await render_broadcast_progress(
            callback.message,
            callback_data.broadcast_id,
            language,
            session_factory,
        )


@router.callback_query(AdminCallback.filter(F.action == "channels"), AdminFilter())
async def manage_channels(
    callback: CallbackQuery,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    if isinstance(callback.message, Message):
        await render_channel_page(callback.message, 0, language, session_factory)


@router.callback_query(ChannelCallback.filter(F.action == "page"), AdminFilter())
async def change_channel_page(
    callback: CallbackQuery,
    callback_data: ChannelCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_channel_page(callback.message, callback_data.page, language, session_factory)


@router.callback_query(ChannelCallback.filter(F.action == "view"), AdminFilter())
async def view_channel(
    callback: CallbackQuery,
    callback_data: ChannelCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    if not isinstance(callback.message, Message):
        await answer_callback_safely(callback)
        return
    found = await render_channel_detail(
        callback.message,
        callback_data.channel_id,
        callback_data.page,
        language,
        session_factory,
    )
    await answer_callback_safely(
        callback,
        None if found else tr(language, "channel_missing"),
        show_alert=not found,
    )


@router.callback_query(ChannelCallback.filter(F.action == "add"), AdminFilter())
async def begin_channel_add(callback: CallbackQuery, state: FSMContext, language: Language) -> None:
    await answer_callback_safely(callback)
    await state.set_state(AdminChannelAdd.waiting_for_id)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "channel_id_prompt"),
            reply_markup=upload_cancel_keyboard(language),
        )


@router.message(
    AdminChannelAdd.waiting_for_id,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
)
async def receive_new_channel_id(
    message: Message,
    bot: Bot,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        validated = await validate_telegram_channel(bot, message.text)
    except ChannelValidationError as exc:
        await message.answer(channel_validation_text(exc, language))
        return
    async with session_factory() as session:
        duplicate = await get_channel_by_chat_id(session, validated.telegram_chat_id)
    if duplicate is not None:
        await message.answer(tr(language, "channel_duplicate"))
        return
    await state.update_data(
        telegram_chat_id=validated.telegram_chat_id,
        title=validated.title,
    )
    await state.set_state(AdminChannelAdd.waiting_for_url)
    await message.answer(
        tr(language, "channel_url_prompt"),
        reply_markup=upload_cancel_keyboard(language),
    )


@router.message(
    AdminChannelAdd.waiting_for_url,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
)
async def receive_new_channel_url(
    message: Message,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        join_url = validate_channel_url(message.text)
    except ValueError:
        await message.answer(tr(language, "channel_invalid_url"))
        return
    data = await state.get_data()
    try:
        async with session_factory.begin() as session:
            channel = await add_channel(
                session,
                telegram_chat_id=str(data["telegram_chat_id"]),
                title=str(data["title"]),
                join_url=join_url,
            )
    except ChannelAlreadyExistsError:
        await state.clear()
        await message.answer(
            tr(language, "channel_duplicate"),
            reply_markup=admin_menu_keyboard(language),
        )
        return
    await state.clear()
    await message.answer(
        tr(language, "channel_added", title=escape(channel.title)),
        reply_markup=admin_menu_keyboard(language),
    )


@router.callback_query(ChannelCallback.filter(F.action.in_({"edit_id", "edit_url"})), AdminFilter())
async def begin_channel_edit(
    callback: CallbackQuery,
    callback_data: ChannelCallback,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        channel = await get_channel(session, callback_data.channel_id)
    if channel is None:
        if isinstance(callback.message, Message):
            await render_channel_page(
                callback.message, callback_data.page, language, session_factory
            )
        await answer_callback_safely(callback, tr(language, "channel_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    await state.update_data(channel_id=channel.id, page=callback_data.page)
    if callback_data.action == "edit_id":
        await state.set_state(AdminChannelEdit.waiting_for_id)
        prompt = tr(language, "channel_id_prompt")
    else:
        await state.set_state(AdminChannelEdit.waiting_for_url)
        prompt = tr(language, "channel_url_prompt")
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            prompt,
            reply_markup=upload_cancel_keyboard(language),
        )


@router.message(
    AdminChannelEdit.waiting_for_id,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
)
async def receive_edited_channel_id(
    message: Message,
    bot: Bot,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        validated = await validate_telegram_channel(bot, message.text)
    except ChannelValidationError as exc:
        await message.answer(channel_validation_text(exc, language))
        return
    data = await state.get_data()
    try:
        async with session_factory.begin() as session:
            channel = await update_channel_identity(
                session,
                int(data["channel_id"]),
                telegram_chat_id=validated.telegram_chat_id,
                title=validated.title,
            )
    except ChannelAlreadyExistsError:
        await message.answer(tr(language, "channel_duplicate"))
        return
    await state.clear()
    if channel is None:
        await message.answer(
            tr(language, "channel_missing"),
            reply_markup=admin_menu_keyboard(language),
        )
        return
    await message.answer(
        tr(language, "channel_updated", title=escape(channel.title)),
        reply_markup=admin_menu_keyboard(language),
    )


@router.message(
    AdminChannelEdit.waiting_for_url,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
)
async def receive_edited_channel_url(
    message: Message,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        join_url = validate_channel_url(message.text)
    except ValueError:
        await message.answer(tr(language, "channel_invalid_url"))
        return
    data = await state.get_data()
    async with session_factory.begin() as session:
        channel = await update_channel_url(session, int(data["channel_id"]), join_url=join_url)
    await state.clear()
    if channel is None:
        await message.answer(
            tr(language, "channel_missing"),
            reply_markup=admin_menu_keyboard(language),
        )
        return
    await message.answer(
        tr(language, "channel_updated", title=escape(channel.title)),
        reply_markup=admin_menu_keyboard(language),
    )


@router.callback_query(ChannelCallback.filter(F.action == "delete_request"), AdminFilter())
async def request_channel_deletion(
    callback: CallbackQuery,
    callback_data: ChannelCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        channel = await get_channel(session, callback_data.channel_id)
    if channel is None:
        if isinstance(callback.message, Message):
            await render_channel_page(
                callback.message, callback_data.page, language, session_factory
            )
        await answer_callback_safely(callback, tr(language, "channel_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "channel_delete_prompt", title=escape(channel.title)),
            reply_markup=channel_delete_keyboard(channel, callback_data.page, language),
        )


@router.callback_query(ChannelCallback.filter(F.action == "delete_confirm"), AdminFilter())
async def confirm_channel_deletion(
    callback: CallbackQuery,
    callback_data: ChannelCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        async with session_factory.begin() as session:
            deleted = await delete_channel(session, callback_data.channel_id)
    except LastChannelDeletionError:
        await answer_callback_safely(
            callback,
            tr(language, "channel_last_delete_forbidden"),
            show_alert=True,
        )
        return
    if isinstance(callback.message, Message):
        await render_channel_page(callback.message, callback_data.page, language, session_factory)
    await answer_callback_safely(
        callback,
        tr(language, "channel_deleted" if deleted else "channel_already_deleted"),
        show_alert=not deleted,
    )


@router.callback_query(AdminCallback.filter())
@router.callback_query(ChannelCallback.filter())
@router.callback_query(BroadcastCallback.filter())
async def reject_admin_callback(
    callback: CallbackQuery, settings: Settings, language: Language
) -> None:
    sender_id = callback.from_user.id if callback.from_user else None
    text = (
        tr(language, "admin_unsupported")
        if is_admin_user(sender_id, settings.admin_ids)
        else tr(language, "admin_action_unauthorized")
    )
    await answer_callback_safely(callback, text, show_alert=True)


@router.callback_query(
    F.data.startswith("admin:") | F.data.startswith("channel:") | F.data.startswith("broadcast:")
)
async def reject_malformed_admin_callback(
    callback: CallbackQuery, settings: Settings, language: Language
) -> None:
    sender_id = callback.from_user.id if callback.from_user else None
    text = (
        tr(language, "admin_callback_stale")
        if is_admin_user(sender_id, settings.admin_ids)
        else tr(language, "admin_action_unauthorized")
    )
    await answer_callback_safely(callback, text, show_alert=True)
