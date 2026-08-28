from __future__ import annotations

from datetime import UTC, datetime

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.callbacks import AdminOptionCallback, OptionItemCallback
from app.bot.handlers import admin_options as handler
from app.bot.states.admin import (
    AdminOptionCreate,
    AdminOptionItemCompose,
    AdminOptionItemTextEdit,
    AdminOptionNameEdit,
)
from app.db.models import MediaType
from app.db.session import Database
from app.i18n import Language
from app.services.options import (
    OptionItemInput,
    create_option,
    get_option,
    get_option_items,
)


def make_message(text: str = "value") -> Message:
    return Message(
        message_id=10,
        date=datetime.now(UTC),
        chat=Chat(id=10, type="private"),
        from_user=User(id=10, is_bot=False, first_name="Admin"),
        text=text,
    )


def make_callback(data: str = "option:view:1:0") -> CallbackQuery:
    return CallbackQuery(
        id="callback-id",
        from_user=User(id=10, is_bot=False, first_name="Admin"),
        chat_instance="private",
        message=make_message("Admin panel"),
        data=data,
    )


def make_state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=10, user_id=10),
    )


def text_input(label: str = "item") -> OptionItemInput:
    return OptionItemInput(
        media_type=MediaType.TEXT,
        telegram_file_id="",
        telegram_file_unique_id=None,
        original_filename=None,
        text_uz=f"uz-{label}",
        text_ru=f"ru-{label}",
        text_en=f"en-{label}",
    )


async def make_option(database: Database, label: str = "option"):
    async with database.session_factory.begin() as session:
        return await create_option(
            session,
            name_uz=f"uz-{label}",
            name_ru=f"ru-{label}",
            name_en=f"en-{label}",
            items=(text_input(label),),
        )


def patch_ui(monkeypatch):
    answers: list[tuple[str, dict]] = []
    edits: list[tuple[str, dict]] = []
    callback_answers: list[tuple[str | None, bool]] = []

    async def answer(_message, text, **kwargs):
        answers.append((text, kwargs))

    async def edit(_message, text, **kwargs):
        edits.append((text, kwargs))

    async def answer_callback(_callback, text=None, *, show_alert=False):
        callback_answers.append((text, show_alert))

    monkeypatch.setattr(Message, "answer", answer)
    monkeypatch.setattr(handler, "edit_text_safely", edit)
    monkeypatch.setattr(handler, "answer_callback_safely", answer_callback)
    return answers, edits, callback_answers


async def complete_one_text_draft(
    state: FSMContext,
    language: Language,
    database: Database,
) -> None:
    await handler.receive_option_content(make_message("Uzbek"), state, language)
    await handler.receive_option_text_ru(make_message("Русский"), state, language)
    await handler.receive_option_text_en(
        make_message("English"), state, language, database.session_factory
    )


async def test_complete_creation_flow_saves_active_localized_option(
    monkeypatch, database: Database
) -> None:
    patch_ui(monkeypatch)
    state = make_state()
    await state.set_state(AdminOptionCreate.waiting_for_name_uz)
    await handler.receive_option_name_uz(make_message("O‘zbek"), state, Language.EN)
    await handler.receive_option_name_ru(make_message("Русский"), state, Language.EN)
    await handler.receive_option_name_en(make_message("English"), state, Language.EN)
    await complete_one_text_draft(state, Language.EN, database)
    assert await state.get_state() == AdminOptionCreate.waiting_for_more.state

    callback_data = AdminOptionCallback(action="create_finish", option_id=0, page=0)
    await handler.continue_or_finish_option_create(
        make_callback(callback_data.pack()),
        callback_data,
        state,
        Language.EN,
        database.session_factory,
    )

    async with database.session_factory() as session:
        options = await handler.list_options(session, page=0)
        items = await get_option_items(session, options.items[0].id)
    assert options.total == 1 and options.items[0].is_active
    assert (options.items[0].name_uz, options.items[0].name_ru, options.items[0].name_en) == (
        "O‘zbek",
        "Русский",
        "English",
    )
    assert (items[0].text_uz, items[0].text_ru, items[0].text_en) == (
        "Uzbek",
        "Русский",
        "English",
    )
    assert await state.get_state() is None


async def test_creation_can_accumulate_multiple_items_before_single_commit(
    monkeypatch, database: Database
) -> None:
    patch_ui(monkeypatch)
    state = make_state()
    await state.update_data(name_uz="uz", name_ru="ru", name_en="en")
    await state.set_state(AdminOptionCreate.waiting_for_content)
    await complete_one_text_draft(state, Language.EN, database)
    more = AdminOptionCallback(action="create_more", option_id=0, page=0)
    await handler.continue_or_finish_option_create(
        make_callback(more.pack()),
        more,
        state,
        Language.EN,
        database.session_factory,
    )
    await complete_one_text_draft(state, Language.EN, database)
    finish = AdminOptionCallback(action="create_finish", option_id=0, page=0)
    await handler.continue_or_finish_option_create(
        make_callback(finish.pack()),
        finish,
        state,
        Language.EN,
        database.session_factory,
    )
    async with database.session_factory() as session:
        option = (await handler.list_options(session, page=0)).items[0]
        items = await get_option_items(session, option.id)
    assert len(items) == 2


@pytest.mark.parametrize("invalid", ["", "   ", "x" * 65])
async def test_creation_rejects_invalid_name_without_advancing_state(
    monkeypatch, invalid: str
) -> None:
    answers, _, _ = patch_ui(monkeypatch)
    state = make_state()
    await state.set_state(AdminOptionCreate.waiting_for_name_uz)
    await handler.receive_option_name_uz(make_message(invalid), state, Language.EN)
    assert await state.get_state() == AdminOptionCreate.waiting_for_name_uz.state
    assert answers


async def test_oversized_draft_content_does_not_advance_state(monkeypatch) -> None:
    answers, _, _ = patch_ui(monkeypatch)
    state = make_state()
    await state.set_state(AdminOptionCreate.waiting_for_content)
    await handler.receive_option_content(make_message("x" * 4097), state, Language.EN)
    assert await state.get_state() == AdminOptionCreate.waiting_for_content.state
    assert any("4096" in text for text, _ in answers)


async def test_finish_callback_rejects_missing_or_stale_draft(
    monkeypatch, database: Database
) -> None:
    _, _, callbacks = patch_ui(monkeypatch)
    state = make_state()
    finish = AdminOptionCallback(action="create_finish", option_id=0, page=0)
    await handler.continue_or_finish_option_create(
        make_callback(finish.pack()),
        finish,
        state,
        Language.EN,
        database.session_factory,
    )
    assert callbacks[-1][1]


@pytest.mark.parametrize("language", list(Language))
async def test_admin_can_edit_each_localized_option_name(
    monkeypatch, database: Database, language: Language
) -> None:
    patch_ui(monkeypatch)
    option = await make_option(database, language.value)
    state = make_state()
    callback_data = AdminOptionCallback(
        action=f"name_{language.value}", option_id=option.id, page=0
    )
    await handler.begin_option_name_edit(
        make_callback(callback_data.pack()),
        callback_data,
        state,
        Language.EN,
        database.session_factory,
    )
    assert await state.get_state() == AdminOptionNameEdit.waiting_for_value.state
    await handler.receive_option_name_edit(
        make_message("Updated"), state, Language.EN, database.session_factory
    )
    async with database.session_factory() as session:
        stored = await get_option(session, option.id)
    assert stored is not None
    assert getattr(stored, f"name_{language.value}") == "Updated"


@pytest.mark.parametrize("language", list(Language))
async def test_admin_can_edit_each_localized_item_text(
    monkeypatch, database: Database, language: Language
) -> None:
    patch_ui(monkeypatch)
    option = await make_option(database, language.value)
    async with database.session_factory() as session:
        item = (await get_option_items(session, option.id))[0]
    state = make_state()
    callback_data = OptionItemCallback(
        action=f"text_{language.value}",
        item_id=item.id,
        option_id=option.id,
        page=0,
        option_page=0,
    )
    await handler.begin_option_item_text_edit(
        make_callback(callback_data.pack()),
        callback_data,
        state,
        Language.EN,
        database.session_factory,
    )
    assert await state.get_state() == AdminOptionItemTextEdit.waiting_for_value.state
    await handler.receive_option_item_text_edit(
        make_message("Updated text"), state, Language.EN, database.session_factory
    )
    async with database.session_factory() as session:
        stored = await handler.get_option_item(session, item.id)
    assert stored is not None
    assert getattr(stored, f"text_{language.value}") == "Updated text"


async def test_add_item_composition_persists_new_item(monkeypatch, database: Database) -> None:
    patch_ui(monkeypatch)
    option = await make_option(database)
    state = make_state()
    callback_data = OptionItemCallback(
        action="add",
        item_id=0,
        option_id=option.id,
        page=0,
        option_page=0,
    )
    await handler.begin_option_item_compose(
        make_callback(callback_data.pack()),
        callback_data,
        state,
        Language.EN,
        database.session_factory,
    )
    assert await state.get_state() == AdminOptionItemCompose.waiting_for_content.state
    await handler.receive_option_content(make_message("New uz"), state, Language.EN)
    await handler.receive_option_text_ru(make_message("New ru"), state, Language.EN)
    await handler.receive_option_text_en(
        make_message("New en"), state, Language.EN, database.session_factory
    )
    async with database.session_factory() as session:
        items = await get_option_items(session, option.id)
    assert len(items) == 2 and items[-1].text_en == "New en"


async def test_replace_item_composition_changes_type_and_payload_atomically(
    monkeypatch, database: Database
) -> None:
    patch_ui(monkeypatch)
    option = await make_option(database)
    async with database.session_factory() as session:
        item = (await get_option_items(session, option.id))[0]
    state = make_state()
    await state.update_data(
        compose_mode="replace",
        option_id=option.id,
        item_id=item.id,
        item_page=0,
        option_page=0,
        media_type=MediaType.TEXT.value,
        telegram_file_id="",
        telegram_file_unique_id=None,
        original_filename=None,
        text_uz="replacement uz",
        text_ru="replacement ru",
    )
    await state.set_state(AdminOptionItemCompose.waiting_for_en)
    await handler.receive_option_text_en(
        make_message("replacement en"), state, Language.EN, database.session_factory
    )
    async with database.session_factory() as session:
        stored = await handler.get_option_item(session, item.id)
    assert stored is not None and stored.id == item.id
    assert stored.text_en == "replacement en"


async def test_last_item_deletion_handler_keeps_option_but_deactivates_it(
    monkeypatch, database: Database
) -> None:
    patch_ui(monkeypatch)
    option = await make_option(database)
    async with database.session_factory() as session:
        item = (await get_option_items(session, option.id))[0]
    callback_data = OptionItemCallback(
        action="delete_confirm",
        item_id=item.id,
        option_id=option.id,
        page=0,
        option_page=0,
    )
    await handler.confirm_option_item_delete(
        make_callback(callback_data.pack()),
        callback_data,
        Language.EN,
        database.session_factory,
    )
    async with database.session_factory() as session:
        stored = await get_option(session, option.id)
        items = await get_option_items(session, option.id)
    assert stored is not None and not stored.is_active and not items


async def test_option_delete_handler_cascades_and_is_idempotent(
    monkeypatch, database: Database
) -> None:
    patch_ui(monkeypatch)
    option = await make_option(database)
    callback_data = AdminOptionCallback(action="delete_confirm", option_id=option.id, page=0)
    callback = make_callback(callback_data.pack())
    await handler.confirm_option_delete(
        callback, callback_data, Language.EN, database.session_factory
    )
    await handler.confirm_option_delete(
        callback, callback_data, Language.EN, database.session_factory
    )
    async with database.session_factory() as session:
        assert await get_option(session, option.id) is None


async def test_toggle_empty_option_returns_alert_without_crashing(
    monkeypatch, database: Database
) -> None:
    _, _, callbacks = patch_ui(monkeypatch)
    option = await make_option(database)
    async with database.session_factory.begin() as session:
        item = (await get_option_items(session, option.id))[0]
        await handler.delete_option_item(session, item.id)
    callback_data = AdminOptionCallback(action="enable", option_id=option.id, page=0)
    await handler.toggle_admin_option(
        make_callback(callback_data.pack()),
        callback_data,
        Language.EN,
        database.session_factory,
    )
    assert callbacks[-1][1]


async def test_render_stale_option_and_item_falls_back_to_current_list(
    monkeypatch, database: Database
) -> None:
    _, edits, _ = patch_ui(monkeypatch)
    message = make_message()
    assert not await handler.render_option_detail(
        message, 999, 0, Language.EN, database.session_factory
    )
    assert not await handler.render_option_item_detail(
        message, 999, 999, 0, 0, Language.EN, database.session_factory
    )
    assert edits


async def test_item_callback_cannot_target_item_from_another_option(
    monkeypatch, database: Database
) -> None:
    _, _, callbacks = patch_ui(monkeypatch)
    first = await make_option(database, "first")
    second = await make_option(database, "second")
    async with database.session_factory() as session:
        item = (await get_option_items(session, first.id))[0]
    state = make_state()
    callback_data = OptionItemCallback(
        action="replace",
        item_id=item.id,
        option_id=second.id,
        page=0,
        option_page=0,
    )
    await handler.begin_option_item_compose(
        make_callback(callback_data.pack()),
        callback_data,
        state,
        Language.EN,
        database.session_factory,
    )
    assert callbacks[-1][1]
    assert await state.get_state() is None


async def test_admin_option_and_item_reordering_actions_are_boundary_safe(
    monkeypatch, database: Database
) -> None:
    patch_ui(monkeypatch)
    option = await make_option(database)
    option_callback = AdminOptionCallback(action="up", option_id=option.id, page=0)
    await handler.reorder_admin_option(
        make_callback(option_callback.pack()),
        option_callback,
        Language.EN,
        database.session_factory,
    )
    async with database.session_factory() as session:
        item = (await get_option_items(session, option.id))[0]
    item_callback = OptionItemCallback(
        action="down",
        item_id=item.id,
        option_id=option.id,
        page=0,
        option_page=0,
    )
    await handler.reorder_option_item(
        make_callback(item_callback.pack()),
        item_callback,
        Language.EN,
        database.session_factory,
    )


async def test_begin_create_clears_old_state_and_prompts_for_first_name(monkeypatch) -> None:
    _, edits, callbacks = patch_ui(monkeypatch)
    state = make_state()
    await state.set_state(AdminOptionItemCompose.waiting_for_content)
    await state.update_data(stale="value")
    await handler.begin_option_create(make_callback("admin:add"), state, Language.EN)
    assert await state.get_state() == AdminOptionCreate.waiting_for_name_uz.state
    assert await state.get_data() == {}
    assert edits and callbacks


async def test_manage_and_navigation_callbacks_render_requested_pages(
    monkeypatch, database: Database
) -> None:
    patch_ui(monkeypatch)
    state = make_state()
    await state.set_state(AdminOptionCreate.waiting_for_name_uz)
    rendered: list[tuple[str, int]] = []

    async def render_page(_message, page, *_args):
        rendered.append(("options", page))

    async def render_item_page(_message, option_id, page, option_page, *_args):
        rendered.append((f"items:{option_id}:{option_page}", page))
        return True

    monkeypatch.setattr(handler, "render_option_page", render_page)
    monkeypatch.setattr(handler, "render_option_item_page", render_item_page)
    await handler.manage_options(
        make_callback("admin:manage"), state, Language.EN, database.session_factory
    )
    option_page = AdminOptionCallback(action="page", option_id=0, page=7)
    await handler.change_admin_option_page(
        make_callback(option_page.pack()),
        option_page,
        Language.EN,
        database.session_factory,
    )
    item_page = OptionItemCallback(action="page", item_id=0, option_id=11, page=3, option_page=2)
    await handler.change_option_item_page(
        make_callback(item_page.pack()),
        item_page,
        Language.EN,
        database.session_factory,
    )
    assert await state.get_state() is None
    assert rendered == [("options", 0), ("options", 7), ("items:11:2", 3)]


@pytest.mark.parametrize(("action", "expected_active"), [("disable", False), ("enable", True)])
async def test_toggle_option_successfully_updates_state(
    monkeypatch, database: Database, action: str, expected_active: bool
) -> None:
    patch_ui(monkeypatch)
    option = await make_option(database, action)
    if action == "enable":
        async with database.session_factory.begin() as session:
            await handler.set_option_active(session, option.id, False)
    callback_data = AdminOptionCallback(action=action, option_id=option.id, page=0)
    await handler.toggle_admin_option(
        make_callback(callback_data.pack()),
        callback_data,
        Language.EN,
        database.session_factory,
    )
    async with database.session_factory() as session:
        stored = await get_option(session, option.id)
    assert stored is not None and stored.is_active is expected_active


async def test_enabling_missing_option_reports_missing_instead_of_empty(
    monkeypatch, database: Database
) -> None:
    _, _, callbacks = patch_ui(monkeypatch)
    callback_data = AdminOptionCallback(action="enable", option_id=999, page=0)
    await handler.toggle_admin_option(
        make_callback(callback_data.pack()),
        callback_data,
        Language.EN,
        database.session_factory,
    )
    assert callbacks[-1][1]
    assert "no longer exists" in (callbacks[-1][0] or "")


async def test_delete_request_callbacks_render_confirmation(
    monkeypatch, database: Database
) -> None:
    _, edits, _ = patch_ui(monkeypatch)
    option = await make_option(database, "<unsafe>")
    async with database.session_factory() as session:
        item = (await get_option_items(session, option.id))[0]
    option_callback = AdminOptionCallback(action="delete_request", option_id=option.id, page=1)
    await handler.request_option_delete(
        make_callback(option_callback.pack()),
        option_callback,
        Language.EN,
        database.session_factory,
    )
    item_callback = OptionItemCallback(
        action="delete_request",
        item_id=item.id,
        option_id=option.id,
        page=0,
        option_page=1,
    )
    await handler.request_option_item_delete(
        make_callback(item_callback.pack()),
        item_callback,
        Language.EN,
        database.session_factory,
    )
    assert len(edits) == 2
    assert "&lt;unsafe&gt;" in edits[0][0]
    assert all(edit[1].get("reply_markup") is not None for edit in edits)


@pytest.mark.parametrize(
    ("state_value", "receiver"),
    [
        (AdminOptionCreate.waiting_for_uz, handler.receive_option_text_uz),
        (AdminOptionCreate.waiting_for_ru, handler.receive_option_text_ru),
    ],
)
async def test_corrupt_localized_content_state_is_recovered(
    monkeypatch, state_value, receiver
) -> None:
    answers, _, _ = patch_ui(monkeypatch)
    state = make_state()
    await state.set_state(state_value)
    await receiver(make_message("text"), state, Language.EN)
    assert await state.get_state() is None
    assert answers and "no longer valid" in answers[-1][0].lower()


async def test_corrupt_final_content_state_is_recovered(monkeypatch, database: Database) -> None:
    answers, _, _ = patch_ui(monkeypatch)
    state = make_state()
    await state.set_state(AdminOptionCreate.waiting_for_en)
    await handler.receive_option_text_en(
        make_message("text"), state, Language.EN, database.session_factory
    )
    assert await state.get_state() is None
    assert answers and "no longer valid" in answers[-1][0].lower()


async def test_waiting_for_more_rejects_free_text_with_controls(monkeypatch) -> None:
    answers, _, _ = patch_ui(monkeypatch)
    await handler.remind_option_creation_controls(make_message("unexpected"), Language.EN)
    assert answers[-1][1].get("reply_markup") is not None
