from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import AdminCallback, ChannelCallback, MediaCallback
from app.bot.filters.admin import AdminFilter, is_admin_user
from app.bot.keyboards.admin import (
    admin_menu_keyboard,
    channel_delete_keyboard,
    channel_detail_keyboard,
    channel_list_keyboard,
    media_delete_keyboard,
    media_detail_keyboard,
    media_list_keyboard,
    upload_cancel_keyboard,
)
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.bot.states.admin import AdminChannelAdd, AdminChannelEdit, AdminUpload
from app.config import Settings
from app.db.models import Channel, Media, MediaType
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr
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
from app.services.media import (
    add_media,
    delete_media,
    get_media,
    list_media,
    set_media_active,
)
from app.validation import validate_channel_url

router = Router(name="admin")


def media_title(item: Media) -> str:
    name = item.original_filename or f"{item.media_type.value}-{item.id}"
    return escape(name)


def media_type_text(item: Media, language: Language) -> str:
    return tr(language, f"media_type_{item.media_type.value}")


def media_detail_text(item: Media, language: Language) -> str:
    status = tr(language, "active" if item.is_active else "inactive")
    return (
        f"<b>{media_title(item)}</b>\n\n"
        f"{tr(language, 'media_type', value=media_type_text(item, language))}\n"
        f"{tr(language, 'media_status', value=status)}\n"
        f"{tr(language, 'media_order', order=item.sort_order)}"
    )


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


async def render_media_page(
    message: Message,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        result = await list_media(session, page=page)
    text = tr(
        language,
        "media_manage_title",
        total=result.total,
        page=result.page + 1,
        pages=result.pages,
    )
    if not result.items:
        text += f"\n\n{tr(language, 'media_empty')}"
    await edit_text_safely(
        message,
        text,
        reply_markup=media_list_keyboard(result, language),
    )


async def render_media_detail(
    message: Message,
    media_id: int,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        item = await get_media(session, media_id)
    if item is None:
        await render_media_page(message, page, language, session_factory)
        return False
    await edit_text_safely(
        message,
        media_detail_text(item, language),
        reply_markup=media_detail_keyboard(item, page, language),
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


@router.callback_query(AdminCallback.filter(F.action == "add"), AdminFilter())
async def begin_media_upload(
    callback: CallbackQuery, state: FSMContext, language: Language
) -> None:
    await answer_callback_safely(callback)
    await state.set_state(AdminUpload.waiting_for_media)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "admin_upload_prompt"),
            reply_markup=upload_cancel_keyboard(language),
        )


@router.message(
    AdminUpload.waiting_for_media,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.video | F.photo | F.document,
)
async def receive_admin_media(
    message: Message,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    if message.video is not None:
        media_type = MediaType.VIDEO
        file_id = message.video.file_id
        unique_id = message.video.file_unique_id
        filename = message.video.file_name
    elif message.photo:
        media_type = MediaType.PHOTO
        largest_photo = message.photo[-1]
        file_id = largest_photo.file_id
        unique_id = largest_photo.file_unique_id
        filename = None
    elif message.document is not None:
        media_type = MediaType.DOCUMENT
        file_id = message.document.file_id
        unique_id = message.document.file_unique_id
        filename = message.document.file_name
    else:
        return

    async with session_factory.begin() as session:
        item = await add_media(
            session,
            telegram_file_id=file_id,
            telegram_file_unique_id=unique_id,
            media_type=media_type,
            original_filename=filename,
            caption=message.caption,
        )

    await state.clear()
    await message.answer(
        tr(
            language,
            "media_added",
            name=media_title(item),
            order=item.sort_order,
        ),
        reply_markup=admin_menu_keyboard(language),
    )


@router.message(
    AdminUpload.waiting_for_media,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
async def reject_unsupported_upload(message: Message, language: Language) -> None:
    await message.answer(
        tr(language, "media_unsupported"),
        reply_markup=upload_cancel_keyboard(language),
    )


@router.message(Command("cancel"), F.chat.type == ChatType.PRIVATE, AdminFilter())
async def cancel_admin_state(message: Message, state: FSMContext, language: Language) -> None:
    await state.clear()
    await message.answer(
        tr(language, "admin_menu"),
        reply_markup=admin_menu_keyboard(language),
    )


@router.callback_query(AdminCallback.filter(F.action == "manage"), AdminFilter())
async def manage_media(
    callback: CallbackQuery,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    if isinstance(callback.message, Message):
        await render_media_page(callback.message, 0, language, session_factory)


@router.callback_query(MediaCallback.filter(F.action == "page"), AdminFilter())
async def change_media_page(
    callback: CallbackQuery,
    callback_data: MediaCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_media_page(callback.message, callback_data.page, language, session_factory)


@router.callback_query(MediaCallback.filter(F.action == "view"), AdminFilter())
async def view_media(
    callback: CallbackQuery,
    callback_data: MediaCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    if not isinstance(callback.message, Message):
        await answer_callback_safely(callback)
        return
    found = await render_media_detail(
        callback.message,
        callback_data.media_id,
        callback_data.page,
        language,
        session_factory,
    )
    await answer_callback_safely(
        callback,
        None if found else tr(language, "media_missing"),
        show_alert=not found,
    )


@router.callback_query(MediaCallback.filter(F.action.in_({"enable", "disable"})), AdminFilter())
async def toggle_media(
    callback: CallbackQuery,
    callback_data: MediaCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    active = callback_data.action == "enable"
    async with session_factory.begin() as session:
        changed = await set_media_active(session, callback_data.media_id, active)

    if isinstance(callback.message, Message):
        if changed:
            await render_media_detail(
                callback.message,
                callback_data.media_id,
                callback_data.page,
                language,
                session_factory,
            )
        else:
            await render_media_page(callback.message, callback_data.page, language, session_factory)
    await answer_callback_safely(
        callback,
        tr(language, "media_enabled" if active else "media_disabled")
        if changed
        else tr(language, "media_missing"),
        show_alert=not changed,
    )


@router.callback_query(MediaCallback.filter(F.action == "delete_request"), AdminFilter())
async def request_media_deletion(
    callback: CallbackQuery,
    callback_data: MediaCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        item = await get_media(session, callback_data.media_id)
    if item is None:
        if isinstance(callback.message, Message):
            await render_media_page(callback.message, callback_data.page, language, session_factory)
        await answer_callback_safely(callback, tr(language, "media_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "media_delete_prompt", name=media_title(item)),
            reply_markup=media_delete_keyboard(item, callback_data.page, language),
        )


@router.callback_query(MediaCallback.filter(F.action == "delete_confirm"), AdminFilter())
async def confirm_media_deletion(
    callback: CallbackQuery,
    callback_data: MediaCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        deleted = await delete_media(session, callback_data.media_id)
    if isinstance(callback.message, Message):
        await render_media_page(callback.message, callback_data.page, language, session_factory)
    await answer_callback_safely(
        callback,
        tr(language, "media_deleted" if deleted else "media_already_deleted"),
        show_alert=not deleted,
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
@router.callback_query(MediaCallback.filter())
@router.callback_query(ChannelCallback.filter())
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
    F.data.startswith("admin:") | F.data.startswith("media:") | F.data.startswith("channel:")
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
