from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import AdminCallback, AdminOptionCallback, OptionItemCallback
from app.bot.content_input import (
    content_validation_text,
    extract_content,
    option_item_input,
)
from app.bot.filters.admin import AdminFilter, is_admin_user
from app.bot.keyboards.admin import (
    admin_menu_keyboard,
    option_creation_more_keyboard,
    option_delete_keyboard,
    option_detail_keyboard,
    option_item_delete_keyboard,
    option_item_detail_keyboard,
    option_items_keyboard,
    option_list_keyboard,
    upload_cancel_keyboard,
)
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.bot.states.admin import (
    AdminOptionCreate,
    AdminOptionItemCompose,
    AdminOptionItemTextEdit,
    AdminOptionNameEdit,
)
from app.config import Settings
from app.db.models import ContentOption, MediaType, OptionContentItem
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr
from app.services.options import (
    EmptyOptionError,
    add_option_item,
    create_option,
    delete_option,
    delete_option_item,
    get_option,
    get_option_item,
    get_option_items,
    list_option_items,
    list_options,
    localized_option_name,
    move_option,
    move_option_item,
    replace_option_item,
    set_option_active,
    update_option_item_text,
    update_option_name,
    validate_option_name,
)

router = Router(name="admin_options")


def option_detail_text(option: ContentOption, item_count: int, language: Language) -> str:
    status = tr(language, "active" if option.is_active else "inactive")
    return tr(
        language,
        "option_detail",
        name_uz=escape(option.name_uz),
        name_ru=escape(option.name_ru),
        name_en=escape(option.name_en),
        status=status,
        count=item_count,
        order=option.sort_order,
    )


def _preview(value: str, limit: int = 220) -> str:
    normalized = value.replace("\n", " ")
    if len(normalized) > limit:
        normalized = f"{normalized[: limit - 3]}..."
    return escape(normalized)


def option_item_detail_text(item: OptionContentItem, language: Language) -> str:
    return tr(
        language,
        "option_item_detail",
        type=tr(language, f"media_type_{item.media_type.value}"),
        text_uz=_preview(item.text_uz),
        text_ru=_preview(item.text_ru),
        text_en=_preview(item.text_en),
        order=item.sort_order,
    )


async def render_option_page(
    message: Message,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        result = await list_options(session, page=page)
    text = tr(
        language,
        "options_manage_title",
        total=result.total,
        page=result.page + 1,
        pages=result.pages,
    )
    if not result.items:
        text += f"\n\n{tr(language, 'options_manage_empty')}"
    await edit_text_safely(
        message,
        text,
        reply_markup=option_list_keyboard(result, language),
    )


async def render_option_detail(
    message: Message,
    option_id: int,
    page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        option = await get_option(session, option_id)
        items = await get_option_items(session, option_id) if option is not None else ()
    if option is None:
        await render_option_page(message, page, language, session_factory)
        return False
    await edit_text_safely(
        message,
        option_detail_text(option, len(items), language),
        reply_markup=option_detail_keyboard(option, page, language),
    )
    return True


async def render_option_item_page(
    message: Message,
    option_id: int,
    item_page: int,
    option_page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        option = await get_option(session, option_id)
        result = (
            await list_option_items(session, option_id=option_id, page=item_page)
            if option is not None
            else None
        )
    if option is None or result is None:
        await render_option_page(message, option_page, language, session_factory)
        return False
    text = tr(
        language,
        "option_items_title",
        name=escape(localized_option_name(option, language)),
        total=result.total,
        page=result.page + 1,
        pages=result.pages,
    )
    if not result.items:
        text += f"\n\n{tr(language, 'option_items_empty')}"
    await edit_text_safely(
        message,
        text,
        reply_markup=option_items_keyboard(option, result, option_page, language),
    )
    return True


async def render_option_item_detail(
    message: Message,
    item_id: int,
    option_id: int,
    item_page: int,
    option_page: int,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> bool:
    async with session_factory() as session:
        item = await get_option_item(session, item_id)
    if item is None or item.option_id != option_id:
        await render_option_item_page(
            message,
            option_id,
            item_page,
            option_page,
            language,
            session_factory,
        )
        return False
    await edit_text_safely(
        message,
        option_item_detail_text(item, language),
        reply_markup=option_item_detail_keyboard(item, item_page, option_page, language),
    )
    return True


@router.callback_query(AdminCallback.filter(F.action == "add"), AdminFilter())
async def begin_option_create(
    callback: CallbackQuery, state: FSMContext, language: Language
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    await state.set_state(AdminOptionCreate.waiting_for_name_uz)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "option_name_uz_prompt"),
            reply_markup=upload_cancel_keyboard(language),
        )


async def _receive_option_name(
    message: Message,
    state: FSMContext,
    language: Language,
    *,
    field: str,
    next_state,
    next_prompt: str,
) -> None:
    try:
        value = validate_option_name(message.text)
    except ValueError:
        await message.answer(tr(language, "option_name_invalid"))
        return
    await state.update_data(**{field: value})
    await state.set_state(next_state)
    await message.answer(
        tr(language, next_prompt),
        reply_markup=upload_cancel_keyboard(language),
    )


@router.message(
    AdminOptionCreate.waiting_for_name_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_option_name_uz(message: Message, state: FSMContext, language: Language) -> None:
    await _receive_option_name(
        message,
        state,
        language,
        field="name_uz",
        next_state=AdminOptionCreate.waiting_for_name_ru,
        next_prompt="option_name_ru_prompt",
    )


@router.message(
    AdminOptionCreate.waiting_for_name_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_option_name_ru(message: Message, state: FSMContext, language: Language) -> None:
    await _receive_option_name(
        message,
        state,
        language,
        field="name_ru",
        next_state=AdminOptionCreate.waiting_for_name_en,
        next_prompt="option_name_en_prompt",
    )


@router.message(
    AdminOptionCreate.waiting_for_name_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_option_name_en(message: Message, state: FSMContext, language: Language) -> None:
    await _receive_option_name(
        message,
        state,
        language,
        field="name_en",
        next_state=AdminOptionCreate.waiting_for_content,
        next_prompt="option_content_prompt",
    )


@router.message(
    AdminOptionCreate.waiting_for_content,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.video | F.photo | F.document | (F.text & ~F.text.startswith("/")),
)
@router.message(
    AdminOptionItemCompose.waiting_for_content,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.video | F.photo | F.document | (F.text & ~F.text.startswith("/")),
)
async def receive_option_content(message: Message, state: FSMContext, language: Language) -> None:
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
    current_state = await state.get_state()
    creating = current_state == AdminOptionCreate.waiting_for_content.state
    if initial_uz is None:
        await state.set_state(
            AdminOptionCreate.waiting_for_uz if creating else AdminOptionItemCompose.waiting_for_uz
        )
        prompt = "content_uz_prompt"
    else:
        await state.update_data(text_uz=initial_uz)
        await state.set_state(
            AdminOptionCreate.waiting_for_ru if creating else AdminOptionItemCompose.waiting_for_ru
        )
        prompt = "content_ru_prompt"
    await message.answer(tr(language, prompt), reply_markup=upload_cancel_keyboard(language))


@router.message(
    AdminOptionCreate.waiting_for_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionItemCompose.waiting_for_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_option_text_uz(message: Message, state: FSMContext, language: Language) -> None:
    data = await state.get_data()
    try:
        media_type = MediaType(str(data["media_type"]))
    except KeyError, ValueError:
        await state.clear()
        await message.answer(tr(language, "option_edit_stale"))
        return
    error_text = content_validation_text(message.text, media_type, language)
    if error_text is not None:
        await message.answer(error_text)
        return
    current_state = await state.get_state()
    creating = current_state == AdminOptionCreate.waiting_for_uz.state
    await state.update_data(text_uz=message.text)
    await state.set_state(
        AdminOptionCreate.waiting_for_ru if creating else AdminOptionItemCompose.waiting_for_ru
    )
    await message.answer(
        tr(language, "content_ru_prompt"),
        reply_markup=upload_cancel_keyboard(language),
    )


@router.message(
    AdminOptionCreate.waiting_for_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionItemCompose.waiting_for_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_option_text_ru(message: Message, state: FSMContext, language: Language) -> None:
    data = await state.get_data()
    try:
        media_type = MediaType(str(data["media_type"]))
    except KeyError, ValueError:
        await state.clear()
        await message.answer(tr(language, "option_edit_stale"))
        return
    error_text = content_validation_text(message.text, media_type, language)
    if error_text is not None:
        await message.answer(error_text)
        return
    current_state = await state.get_state()
    creating = current_state == AdminOptionCreate.waiting_for_ru.state
    await state.update_data(text_ru=message.text)
    await state.set_state(
        AdminOptionCreate.waiting_for_en if creating else AdminOptionItemCompose.waiting_for_en
    )
    await message.answer(
        tr(language, "content_en_prompt"),
        reply_markup=upload_cancel_keyboard(language),
    )


@router.message(
    AdminOptionCreate.waiting_for_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionItemCompose.waiting_for_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_option_text_en(
    message: Message,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    data = await state.get_data()
    try:
        media_type = MediaType(str(data["media_type"]))
    except KeyError, ValueError:
        await state.clear()
        await message.answer(tr(language, "option_edit_stale"))
        return
    error_text = content_validation_text(message.text, media_type, language)
    if error_text is not None:
        await message.answer(error_text)
        return
    data["text_en"] = message.text
    current_state = await state.get_state()
    if current_state == AdminOptionCreate.waiting_for_en.state:
        draft_items = list(data.get("draft_items", []))
        draft_items.append(
            {
                key: data.get(key)
                for key in (
                    "media_type",
                    "telegram_file_id",
                    "telegram_file_unique_id",
                    "original_filename",
                    "text_uz",
                    "text_ru",
                    "text_en",
                )
            }
        )
        await state.update_data(draft_items=draft_items)
        await state.set_state(AdminOptionCreate.waiting_for_more)
        await message.answer(
            tr(language, "option_item_draft_added", count=len(draft_items)),
            reply_markup=option_creation_more_keyboard(language),
        )
        return

    try:
        item_input = option_item_input(data)
        mode = str(data["compose_mode"])
        if mode not in {"add", "replace"}:
            raise ValueError("invalid composition mode")
        option_id = int(data["option_id"])
        item_page = int(data["item_page"])
        option_page = int(data["option_page"])
        replace_item_id = int(data["item_id"]) if mode == "replace" else None
    except KeyError, TypeError, ValueError:
        await state.clear()
        await message.answer(
            tr(language, "option_edit_stale"),
            reply_markup=admin_menu_keyboard(language),
        )
        return
    async with session_factory.begin() as session:
        if mode == "add":
            item = await add_option_item(session, option_id, item_input)
        else:
            existing = await get_option_item(session, replace_item_id or 0)
            item = (
                await replace_option_item(session, existing.id, item_input)
                if existing is not None and existing.option_id == option_id
                else None
            )
    await state.clear()
    if item is None:
        await message.answer(
            tr(language, "option_item_missing"),
            reply_markup=admin_menu_keyboard(language),
        )
        return
    await message.answer(
        tr(language, "option_item_saved"),
        reply_markup=option_item_detail_keyboard(item, item_page, option_page, language),
    )


@router.callback_query(
    AdminOptionCallback.filter(F.action.in_({"create_more", "create_finish"})),
    AdminFilter(),
)
async def continue_or_finish_option_create(
    callback: CallbackQuery,
    callback_data: AdminOptionCallback,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    if await state.get_state() != AdminOptionCreate.waiting_for_more.state:
        await answer_callback_safely(callback, tr(language, "option_edit_stale"), show_alert=True)
        return
    await answer_callback_safely(callback)
    if callback_data.action == "create_more":
        await state.set_state(AdminOptionCreate.waiting_for_content)
        if isinstance(callback.message, Message):
            await edit_text_safely(
                callback.message,
                tr(language, "option_content_prompt"),
                reply_markup=upload_cancel_keyboard(language),
            )
        return

    data = await state.get_data()
    try:
        draft_items = tuple(option_item_input(item) for item in data["draft_items"])
        async with session_factory.begin() as session:
            option = await create_option(
                session,
                name_uz=str(data["name_uz"]),
                name_ru=str(data["name_ru"]),
                name_en=str(data["name_en"]),
                items=draft_items,
            )
    except KeyError, TypeError, ValueError:
        await state.clear()
        if isinstance(callback.message, Message):
            await edit_text_safely(
                callback.message,
                tr(language, "option_edit_stale"),
                reply_markup=admin_menu_keyboard(language),
            )
        return
    await state.clear()
    if isinstance(callback.message, Message):
        await render_option_detail(callback.message, option.id, 0, language, session_factory)


@router.callback_query(AdminCallback.filter(F.action == "manage"), AdminFilter())
async def manage_options(
    callback: CallbackQuery,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    await state.clear()
    if isinstance(callback.message, Message):
        await render_option_page(callback.message, 0, language, session_factory)


@router.callback_query(AdminOptionCallback.filter(F.action == "page"), AdminFilter())
async def change_admin_option_page(
    callback: CallbackQuery,
    callback_data: AdminOptionCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_option_page(callback.message, callback_data.page, language, session_factory)


@router.callback_query(AdminOptionCallback.filter(F.action == "view"), AdminFilter())
async def view_admin_option(
    callback: CallbackQuery,
    callback_data: AdminOptionCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    if not isinstance(callback.message, Message):
        await answer_callback_safely(callback)
        return
    found = await render_option_detail(
        callback.message,
        callback_data.option_id,
        callback_data.page,
        language,
        session_factory,
    )
    await answer_callback_safely(
        callback,
        None if found else tr(language, "option_missing"),
        show_alert=not found,
    )


@router.callback_query(
    AdminOptionCallback.filter(F.action.in_({"enable", "disable"})), AdminFilter()
)
async def toggle_admin_option(
    callback: CallbackQuery,
    callback_data: AdminOptionCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    active = callback_data.action == "enable"
    try:
        async with session_factory.begin() as session:
            changed = await set_option_active(session, callback_data.option_id, active)
    except EmptyOptionError:
        await answer_callback_safely(
            callback, tr(language, "option_empty_enable_forbidden"), show_alert=True
        )
        return
    if isinstance(callback.message, Message):
        await render_option_detail(
            callback.message,
            callback_data.option_id,
            callback_data.page,
            language,
            session_factory,
        )
    await answer_callback_safely(
        callback,
        tr(language, "option_enabled" if active else "option_disabled")
        if changed
        else tr(language, "option_missing"),
        show_alert=not changed,
    )


@router.callback_query(AdminOptionCallback.filter(F.action.in_({"up", "down"})), AdminFilter())
async def reorder_admin_option(
    callback: CallbackQuery,
    callback_data: AdminOptionCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        moved = await move_option(
            session, callback_data.option_id, -1 if callback_data.action == "up" else 1
        )
    if isinstance(callback.message, Message):
        await render_option_detail(
            callback.message,
            callback_data.option_id,
            callback_data.page,
            language,
            session_factory,
        )
    await answer_callback_safely(
        callback,
        tr(language, "option_reordered" if moved else "option_order_boundary"),
    )


@router.callback_query(AdminOptionCallback.filter(F.action.startswith("name_")), AdminFilter())
async def begin_option_name_edit(
    callback: CallbackQuery,
    callback_data: AdminOptionCallback,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        edit_language = Language(callback_data.action.removeprefix("name_"))
    except ValueError:
        await answer_callback_safely(callback, tr(language, "option_edit_stale"), show_alert=True)
        return
    async with session_factory() as session:
        option = await get_option(session, callback_data.option_id)
    if option is None:
        await answer_callback_safely(callback, tr(language, "option_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    await state.clear()
    await state.update_data(
        option_id=option.id,
        option_page=callback_data.page,
        edit_language=edit_language.value,
    )
    await state.set_state(AdminOptionNameEdit.waiting_for_value)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "option_name_edit_prompt", code=edit_language.value.upper()),
            reply_markup=upload_cancel_keyboard(language),
        )


@router.message(
    AdminOptionNameEdit.waiting_for_value,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_option_name_edit(
    message: Message,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        value = validate_option_name(message.text)
    except ValueError:
        await message.answer(tr(language, "option_name_invalid"))
        return
    data = await state.get_data()
    try:
        option_id = int(data["option_id"])
        option_page = int(data["option_page"])
        edit_language = Language(str(data["edit_language"]))
    except KeyError, TypeError, ValueError:
        await state.clear()
        await message.answer(tr(language, "option_edit_stale"))
        return
    async with session_factory.begin() as session:
        option = await update_option_name(session, option_id, edit_language, value)
    await state.clear()
    if option is None:
        await message.answer(
            tr(language, "option_missing"),
            reply_markup=admin_menu_keyboard(language),
        )
        return
    await message.answer(
        tr(language, "option_name_updated"),
        reply_markup=option_detail_keyboard(option, option_page, language),
    )


@router.callback_query(AdminOptionCallback.filter(F.action == "items"), AdminFilter())
async def manage_option_items(
    callback: CallbackQuery,
    callback_data: AdminOptionCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    if not isinstance(callback.message, Message):
        await answer_callback_safely(callback)
        return
    found = await render_option_item_page(
        callback.message,
        callback_data.option_id,
        0,
        callback_data.page,
        language,
        session_factory,
    )
    await answer_callback_safely(
        callback,
        None if found else tr(language, "option_missing"),
        show_alert=not found,
    )


@router.callback_query(OptionItemCallback.filter(F.action == "page"), AdminFilter())
async def change_option_item_page(
    callback: CallbackQuery,
    callback_data: OptionItemCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await render_option_item_page(
            callback.message,
            callback_data.option_id,
            callback_data.page,
            callback_data.option_page,
            language,
            session_factory,
        )


@router.callback_query(OptionItemCallback.filter(F.action == "view"), AdminFilter())
async def view_option_item(
    callback: CallbackQuery,
    callback_data: OptionItemCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    if not isinstance(callback.message, Message):
        await answer_callback_safely(callback)
        return
    found = await render_option_item_detail(
        callback.message,
        callback_data.item_id,
        callback_data.option_id,
        callback_data.page,
        callback_data.option_page,
        language,
        session_factory,
    )
    await answer_callback_safely(
        callback,
        None if found else tr(language, "option_item_missing"),
        show_alert=not found,
    )


@router.callback_query(OptionItemCallback.filter(F.action.in_({"add", "replace"})), AdminFilter())
async def begin_option_item_compose(
    callback: CallbackQuery,
    callback_data: OptionItemCallback,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        option = await get_option(session, callback_data.option_id)
        item = (
            await get_option_item(session, callback_data.item_id)
            if callback_data.action == "replace"
            else None
        )
    if option is None or (
        callback_data.action == "replace"
        and (item is None or item.option_id != callback_data.option_id)
    ):
        await answer_callback_safely(callback, tr(language, "option_item_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    await state.clear()
    await state.update_data(
        compose_mode=callback_data.action,
        option_id=callback_data.option_id,
        item_id=callback_data.item_id,
        item_page=callback_data.page,
        option_page=callback_data.option_page,
    )
    await state.set_state(AdminOptionItemCompose.waiting_for_content)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "option_content_prompt"),
            reply_markup=upload_cancel_keyboard(language),
        )


@router.callback_query(OptionItemCallback.filter(F.action.startswith("text_")), AdminFilter())
async def begin_option_item_text_edit(
    callback: CallbackQuery,
    callback_data: OptionItemCallback,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    try:
        edit_language = Language(callback_data.action.removeprefix("text_"))
    except ValueError:
        await answer_callback_safely(callback, tr(language, "option_edit_stale"), show_alert=True)
        return
    async with session_factory() as session:
        item = await get_option_item(session, callback_data.item_id)
    if item is None or item.option_id != callback_data.option_id:
        await answer_callback_safely(callback, tr(language, "option_item_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    await state.clear()
    await state.update_data(
        item_id=item.id,
        option_id=item.option_id,
        item_page=callback_data.page,
        option_page=callback_data.option_page,
        edit_language=edit_language.value,
    )
    await state.set_state(AdminOptionItemTextEdit.waiting_for_value)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "option_text_edit_prompt", code=edit_language.value.upper()),
            reply_markup=upload_cancel_keyboard(language),
        )


@router.message(
    AdminOptionItemTextEdit.waiting_for_value,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_option_item_text_edit(
    message: Message,
    state: FSMContext,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    data = await state.get_data()
    try:
        item_id = int(data["item_id"])
        option_id = int(data["option_id"])
        item_page = int(data["item_page"])
        option_page = int(data["option_page"])
        edit_language = Language(str(data["edit_language"]))
    except KeyError, TypeError, ValueError:
        await state.clear()
        await message.answer(tr(language, "option_edit_stale"))
        return
    async with session_factory() as session:
        current_item = await get_option_item(session, item_id)
    if current_item is None or current_item.option_id != option_id:
        await state.clear()
        await message.answer(
            tr(language, "option_item_missing"),
            reply_markup=admin_menu_keyboard(language),
        )
        return
    error_text = content_validation_text(message.text, current_item.media_type, language)
    if error_text is not None:
        await message.answer(error_text)
        return
    async with session_factory.begin() as session:
        item = await update_option_item_text(session, item_id, edit_language, message.text or "")
    await state.clear()
    if item is None:
        await message.answer(
            tr(language, "option_item_missing"),
            reply_markup=admin_menu_keyboard(language),
        )
        return
    await message.answer(
        tr(language, "option_item_text_updated"),
        reply_markup=option_item_detail_keyboard(item, item_page, option_page, language),
    )


@router.callback_query(OptionItemCallback.filter(F.action.in_({"up", "down"})), AdminFilter())
async def reorder_option_item(
    callback: CallbackQuery,
    callback_data: OptionItemCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        item = await get_option_item(session, callback_data.item_id)
        moved = (
            await move_option_item(
                session,
                callback_data.item_id,
                -1 if callback_data.action == "up" else 1,
            )
            if item is not None and item.option_id == callback_data.option_id
            else False
        )
    if isinstance(callback.message, Message):
        await render_option_item_detail(
            callback.message,
            callback_data.item_id,
            callback_data.option_id,
            callback_data.page,
            callback_data.option_page,
            language,
            session_factory,
        )
    await answer_callback_safely(
        callback,
        tr(language, "option_reordered" if moved else "option_order_boundary"),
    )


@router.callback_query(AdminOptionCallback.filter(F.action == "delete_request"), AdminFilter())
async def request_option_delete(
    callback: CallbackQuery,
    callback_data: AdminOptionCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        option = await get_option(session, callback_data.option_id)
    if option is None:
        await answer_callback_safely(callback, tr(language, "option_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(
                language,
                "option_delete_prompt",
                name=escape(localized_option_name(option, language)),
            ),
            reply_markup=option_delete_keyboard(option, callback_data.page, language),
        )


@router.callback_query(AdminOptionCallback.filter(F.action == "delete_confirm"), AdminFilter())
async def confirm_option_delete(
    callback: CallbackQuery,
    callback_data: AdminOptionCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        deleted = await delete_option(session, callback_data.option_id)
    if isinstance(callback.message, Message):
        await render_option_page(callback.message, callback_data.page, language, session_factory)
    await answer_callback_safely(
        callback,
        tr(language, "option_deleted" if deleted else "option_already_deleted"),
        show_alert=not deleted,
    )


@router.callback_query(OptionItemCallback.filter(F.action == "delete_request"), AdminFilter())
async def request_option_item_delete(
    callback: CallbackQuery,
    callback_data: OptionItemCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        item = await get_option_item(session, callback_data.item_id)
    if item is None or item.option_id != callback_data.option_id:
        await answer_callback_safely(callback, tr(language, "option_item_missing"), show_alert=True)
        return
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(language, "option_item_delete_prompt"),
            reply_markup=option_item_delete_keyboard(
                item, callback_data.page, callback_data.option_page, language
            ),
        )


@router.callback_query(OptionItemCallback.filter(F.action == "delete_confirm"), AdminFilter())
async def confirm_option_item_delete(
    callback: CallbackQuery,
    callback_data: OptionItemCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory.begin() as session:
        item = await get_option_item(session, callback_data.item_id)
        if item is None or item.option_id != callback_data.option_id:
            deleted = False
        else:
            deleted, _option_id = await delete_option_item(session, callback_data.item_id)
    if isinstance(callback.message, Message):
        await render_option_item_page(
            callback.message,
            callback_data.option_id,
            callback_data.page,
            callback_data.option_page,
            language,
            session_factory,
        )
    await answer_callback_safely(
        callback,
        tr(
            language,
            "option_item_deleted" if deleted else "option_item_already_deleted",
        ),
        show_alert=not deleted,
    )


@router.message(
    AdminOptionCreate.waiting_for_content,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionItemCompose.waiting_for_content,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionCreate.waiting_for_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionCreate.waiting_for_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionCreate.waiting_for_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionItemCompose.waiting_for_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionItemCompose.waiting_for_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionItemCompose.waiting_for_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
async def reject_option_content_input(message: Message, language: Language) -> None:
    await message.answer(
        tr(language, "content_unsupported"),
        reply_markup=upload_cancel_keyboard(language),
    )


@router.message(
    AdminOptionCreate.waiting_for_name_uz,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionCreate.waiting_for_name_ru,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionCreate.waiting_for_name_en,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionNameEdit.waiting_for_value,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
@router.message(
    AdminOptionItemTextEdit.waiting_for_value,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
async def reject_option_text_input(message: Message, language: Language) -> None:
    await message.answer(tr(language, "option_text_required"))


@router.message(
    AdminOptionCreate.waiting_for_more,
    F.chat.type == ChatType.PRIVATE,
    AdminFilter(),
    ~F.text.startswith("/"),
)
async def remind_option_creation_controls(message: Message, language: Language) -> None:
    await message.answer(
        tr(language, "option_use_buttons"),
        reply_markup=option_creation_more_keyboard(language),
    )


@router.callback_query(AdminOptionCallback.filter())
@router.callback_query(OptionItemCallback.filter())
async def reject_option_admin_callback(
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
    F.data.startswith("option:") | F.data.startswith("item:") | F.data.startswith("media:")
)
async def reject_malformed_option_admin_callback(
    callback: CallbackQuery, settings: Settings, language: Language
) -> None:
    sender_id = callback.from_user.id if callback.from_user else None
    text = (
        tr(language, "admin_callback_stale")
        if is_admin_user(sender_id, settings.admin_ids)
        else tr(language, "admin_action_unauthorized")
    )
    await answer_callback_safely(callback, text, show_alert=True)
