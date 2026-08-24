from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import AdminCallback, MediaCallback
from app.bot.filters.admin import AdminFilter, is_admin_user
from app.bot.keyboards.admin import (
    admin_menu_keyboard,
    media_delete_keyboard,
    media_detail_keyboard,
    media_list_keyboard,
    upload_cancel_keyboard,
)
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.bot.states.admin import AdminUpload
from app.config import Settings
from app.db.models import Media, MediaType
from app.db.session import AsyncSessionFactory
from app.services.media import (
    add_media,
    delete_media,
    get_media,
    list_media,
    set_media_active,
)

router = Router(name="admin")

ADMIN_MENU_TEXT = "⚙️ <b>Administration</b>\n\nChoose an action."
UPLOAD_TEXT = "📤 Send one video, photo, or document to add it to the active media list."


def media_title(item: Media) -> str:
    name = item.original_filename or f"{item.media_type.value}-{item.id}"
    return escape(name)


def media_detail_text(item: Media) -> str:
    status = "🟢 Active" if item.is_active else "🔴 Inactive"
    return (
        f"<b>{media_title(item)}</b>\n\n"
        f"Type: {item.media_type.value.title()}\n"
        f"Status: {status}\n"
        f"Order: {item.sort_order}"
    )


async def render_media_page(
    message: Message, page: int, session_factory: AsyncSessionFactory
) -> None:
    async with session_factory() as session:
        result = await list_media(session, page=page)
    text = (
        f"📚 <b>Manage media</b>\n\n{result.total} item(s) · Page {result.page + 1}/{result.pages}"
    )
    if not result.items:
        text += "\n\nNo media has been added yet."
    await edit_text_safely(message, text, reply_markup=media_list_keyboard(result))


async def render_media_detail(
    message: Message,
    media_id: int,
    page: int,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        item = await get_media(session, media_id)
    if item is None:
        await render_media_page(message, page, session_factory)
        return False
    await edit_text_safely(
        message,
        media_detail_text(item),
        reply_markup=media_detail_keyboard(item, page),
    )
    return True


@router.message(
    Command("admin"),
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
)
async def admin_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(ADMIN_MENU_TEXT, reply_markup=admin_menu_keyboard())


@router.message(Command("admin"))
async def reject_admin_command(message: Message, settings: Settings) -> None:
    sender_id = message.from_user.id if message.from_user else None
    if not is_admin_user(sender_id, settings.admin_ids):
        await message.answer("You are not authorized to use administrator commands.")
    else:
        await message.answer("Please use the administrator interface in a private chat.")


@router.callback_query(
    AdminCallback.filter(F.action == "menu"),
    AdminFilter(),
)
async def return_to_admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            ADMIN_MENU_TEXT,
            reply_markup=admin_menu_keyboard(),
        )


@router.callback_query(
    AdminCallback.filter(F.action == "add"),
    AdminFilter(),
)
async def begin_media_upload(callback: CallbackQuery, state: FSMContext) -> None:
    await answer_callback_safely(callback)
    await state.set_state(AdminUpload.waiting_for_media)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            UPLOAD_TEXT,
            reply_markup=upload_cancel_keyboard(),
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
        f"✅ Added <b>{media_title(item)}</b> as active media with order {item.sort_order}.",
        reply_markup=admin_menu_keyboard(),
    )


@router.message(
    AdminUpload.waiting_for_media,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
async def reject_unsupported_upload(message: Message) -> None:
    await message.answer(
        "Unsupported upload. Please send one video, photo, or document, or go back.",
        reply_markup=upload_cancel_keyboard(),
    )


@router.message(
    Command("cancel"),
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
)
async def cancel_admin_state(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(ADMIN_MENU_TEXT, reply_markup=admin_menu_keyboard())


@router.callback_query(
    AdminCallback.filter(F.action == "manage"),
    AdminFilter(),
)
async def manage_media(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    if isinstance(callback.message, Message):
        await render_media_page(callback.message, 0, session_factory)


@router.callback_query(
    MediaCallback.filter(F.action == "page"),
    AdminFilter(),
)
async def change_media_page(
    callback: CallbackQuery,
    callback_data: MediaCallback,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_media_page(callback.message, callback_data.page, session_factory)


@router.callback_query(
    MediaCallback.filter(F.action == "view"),
    AdminFilter(),
)
async def view_media(
    callback: CallbackQuery,
    callback_data: MediaCallback,
    session_factory: AsyncSessionFactory,
) -> None:
    if not isinstance(callback.message, Message):
        await answer_callback_safely(callback)
        return
    found = await render_media_detail(
        callback.message,
        callback_data.media_id,
        callback_data.page,
        session_factory,
    )
    await answer_callback_safely(
        callback,
        None if found else "This media no longer exists.",
        show_alert=not found,
    )


@router.callback_query(
    MediaCallback.filter(F.action.in_({"enable", "disable"})),
    AdminFilter(),
)
async def toggle_media(
    callback: CallbackQuery,
    callback_data: MediaCallback,
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
                session_factory,
            )
        else:
            await render_media_page(callback.message, callback_data.page, session_factory)
    await answer_callback_safely(
        callback,
        ("Media enabled." if active else "Media disabled.")
        if changed
        else "This media no longer exists.",
        show_alert=not changed,
    )


@router.callback_query(
    MediaCallback.filter(F.action == "delete_request"),
    AdminFilter(),
)
async def request_media_deletion(
    callback: CallbackQuery,
    callback_data: MediaCallback,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        item = await get_media(session, callback_data.media_id)
    if item is None:
        if isinstance(callback.message, Message):
            await render_media_page(callback.message, callback_data.page, session_factory)
        await answer_callback_safely(callback, "This media no longer exists.", show_alert=True)
        return
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            f"Delete <b>{media_title(item)}</b>?\n\nThis removes only the database record.",
            reply_markup=media_delete_keyboard(item, callback_data.page),
        )


@router.callback_query(
    MediaCallback.filter(F.action == "delete_confirm"),
    AdminFilter(),
)
async def confirm_media_deletion(
    callback: CallbackQuery,
    callback_data: MediaCallback,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        deleted = await delete_media(session, callback_data.media_id)
    if isinstance(callback.message, Message):
        await render_media_page(callback.message, callback_data.page, session_factory)
    await answer_callback_safely(
        callback,
        "Media deleted." if deleted else "This media was already deleted.",
        show_alert=not deleted,
    )


@router.callback_query(AdminCallback.filter())
@router.callback_query(MediaCallback.filter())
async def reject_admin_callback(callback: CallbackQuery, settings: Settings) -> None:
    sender_id = callback.from_user.id if callback.from_user else None
    text = (
        "Unsupported administrator action."
        if is_admin_user(sender_id, settings.admin_ids)
        else "You are not authorized to perform this action."
    )
    await answer_callback_safely(callback, text, show_alert=True)


@router.callback_query(F.data.startswith("admin:") | F.data.startswith("media:"))
async def reject_malformed_admin_callback(callback: CallbackQuery, settings: Settings) -> None:
    sender_id = callback.from_user.id if callback.from_user else None
    text = (
        "This administrator action is no longer valid."
        if is_admin_user(sender_id, settings.admin_ids)
        else "You are not authorized to perform this action."
    )
    await answer_callback_safely(callback, text, show_alert=True)
