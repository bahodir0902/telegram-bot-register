from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendVideo
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import func, select

from app.db.models import ContentOption, MediaType, OptionContentItem
from app.db.session import Database
from app.i18n import Language
from app.services.content import (
    CAPTION_LIMIT,
    TEXT_LIMIT,
    ContentValidationError,
    localized_content_text,
    send_content,
    validate_content_text,
)
from app.services.options import (
    EmptyOptionError,
    OptionItemInput,
    add_option_item,
    create_option,
    delete_option,
    delete_option_item,
    deliver_option_items,
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
    validate_item_input,
    validate_option_name,
)


def item_input(
    label: str,
    media_type: MediaType = MediaType.TEXT,
    *,
    file_id: str | None = None,
) -> OptionItemInput:
    resolved_file_id = (
        file_id
        if file_id is not None
        else ("" if media_type == MediaType.TEXT else f"file-{label}")
    )
    return OptionItemInput(
        media_type=media_type,
        telegram_file_id=resolved_file_id,
        telegram_file_unique_id=(None if media_type == MediaType.TEXT else f"unique-{label}"),
        original_filename=(
            None if media_type in {MediaType.TEXT, MediaType.PHOTO} else f"{label}.bin"
        ),
        text_uz=f"uz-{label}",
        text_ru=f"ru-{label}",
        text_en=f"en-{label}",
    )


async def make_option(
    database: Database,
    label: str,
    *items: OptionItemInput,
) -> ContentOption:
    async with database.session_factory.begin() as session:
        return await create_option(
            session,
            name_uz=f"uz-{label}",
            name_ru=f"ru-{label}",
            name_en=f"en-{label}",
            items=tuple(items) or (item_input(label),),
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A", "A"),
        ("  Trim me  ", "Trim me"),
        ("x" * 64, "x" * 64),
        ("Tibbiy maslahat", "Tibbiy maslahat"),
    ],
)
def test_validate_option_name_accepts_supported_values(raw: str, expected: str) -> None:
    assert validate_option_name(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "x" * 65])
def test_validate_option_name_rejects_invalid_values(raw: str | None) -> None:
    with pytest.raises(ValueError):
        validate_option_name(raw)


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (Language.UZ, "O‘zbekcha"),
        (Language.RU, "Русский"),
        (Language.EN, "English"),
        ("invalid", "O‘zbekcha"),
        (None, "O‘zbekcha"),
    ],
)
def test_localized_option_name_uses_selected_language_or_default(language, expected: str) -> None:
    option = ContentOption(
        name_uz="O‘zbekcha",
        name_ru="Русский",
        name_en="English",
        is_active=True,
        sort_order=10,
    )
    assert localized_option_name(option, language) == expected


@pytest.mark.parametrize(
    ("media_type", "length"),
    [
        (MediaType.TEXT, TEXT_LIMIT),
        (MediaType.PHOTO, CAPTION_LIMIT),
        (MediaType.VIDEO, CAPTION_LIMIT),
        (MediaType.DOCUMENT, CAPTION_LIMIT),
    ],
)
def test_content_validation_accepts_exact_telegram_limits(
    media_type: MediaType, length: int
) -> None:
    assert validate_content_text("x" * length, media_type)


@pytest.mark.parametrize(
    ("value", "media_type"),
    [
        (None, MediaType.TEXT),
        (" ", MediaType.TEXT),
        ("x" * (TEXT_LIMIT + 1), MediaType.TEXT),
        ("x" * (CAPTION_LIMIT + 1), MediaType.PHOTO),
        ("x" * (CAPTION_LIMIT + 1), MediaType.VIDEO),
        ("x" * (CAPTION_LIMIT + 1), MediaType.DOCUMENT),
    ],
)
def test_content_validation_rejects_empty_and_oversized_values(
    value: str | None, media_type: MediaType
) -> None:
    with pytest.raises(ContentValidationError):
        validate_content_text(value, media_type)


@pytest.mark.parametrize(
    ("media_type", "method_name"),
    [
        (MediaType.TEXT, "send_message"),
        (MediaType.PHOTO, "send_photo"),
        (MediaType.VIDEO, "send_video"),
        (MediaType.DOCUMENT, "send_document"),
    ],
)
async def test_send_content_dispatches_every_supported_type_and_escapes_html(
    media_type: MediaType, method_name: str
) -> None:
    bot = AsyncMock()
    await send_content(
        bot,
        42,
        media_type=media_type,
        telegram_file_id="file-id",
        text="<unsafe>",
    )
    method = getattr(bot, method_name)
    method.assert_awaited_once()
    if media_type == MediaType.TEXT:
        assert method.await_args.args == (42, "&lt;unsafe&gt;")
    else:
        assert method.await_args.args == (42, "file-id")
        assert method.await_args.kwargs["caption"] == "&lt;unsafe&gt;"


async def test_send_content_splits_long_text_and_attaches_markup_to_last_chunk() -> None:
    bot = AsyncMock()
    markup = InlineKeyboardMarkup(inline_keyboard=[])

    await send_content(
        bot,
        42,
        media_type=MediaType.TEXT,
        telegram_file_id="",
        text="x" * 10_000,
        reply_markup=markup,
    )

    assert [call.args for call in bot.send_message.await_args_list] == [
        (42, "x" * 4096),
        (42, "x" * 4096),
        (42, "x" * 1808),
    ]
    assert [call.kwargs for call in bot.send_message.await_args_list] == [
        {},
        {},
        {"reply_markup": markup},
    ]


async def test_send_content_moves_media_content_after_the_caption_limit() -> None:
    bot = AsyncMock()
    markup = InlineKeyboardMarkup(inline_keyboard=[])

    await send_content(
        bot,
        42,
        media_type=MediaType.PHOTO,
        telegram_file_id="file-id",
        text="x" * 4096,
        reply_markup=markup,
    )

    bot.send_photo.assert_awaited_once_with(42, "file-id", caption="x" * 1024)
    bot.send_message.assert_awaited_once_with(42, "x" * 3072, reply_markup=markup)


def test_localized_content_never_silently_falls_back_to_another_authored_language() -> None:
    item = OptionContentItem(
        option_id=1,
        media_type=MediaType.TEXT,
        telegram_file_id="",
        text_uz="Uzbek",
        text_ru="",
        text_en="English",
        sort_order=10,
    )
    assert localized_content_text(item, Language.RU) == ""
    assert localized_content_text(item, "invalid") == "Uzbek"


def test_media_item_requires_file_id_but_text_does_not() -> None:
    assert validate_item_input(item_input("text", MediaType.TEXT))
    with pytest.raises(ValueError, match="file ID"):
        validate_item_input(item_input("photo", MediaType.PHOTO, file_id=""))


async def test_create_option_persists_localized_names_and_ordered_mixed_items(
    database: Database,
) -> None:
    option = await make_option(
        database,
        "mixed",
        item_input("one", MediaType.TEXT),
        item_input("two", MediaType.PHOTO),
        item_input("three", MediaType.VIDEO),
        item_input("four", MediaType.DOCUMENT),
    )
    async with database.session_factory() as session:
        stored = await get_option(session, option.id)
        items = await get_option_items(session, option.id)
    assert stored is not None and stored.is_active
    assert (stored.name_uz, stored.name_ru, stored.name_en) == (
        "uz-mixed",
        "ru-mixed",
        "en-mixed",
    )
    assert [item.media_type for item in items] == [
        MediaType.TEXT,
        MediaType.PHOTO,
        MediaType.VIDEO,
        MediaType.DOCUMENT,
    ]
    assert [item.sort_order for item in items] == [10, 20, 30, 40]


async def test_create_option_rejects_empty_collection_without_partial_row(
    database: Database,
) -> None:
    with pytest.raises(EmptyOptionError):
        async with database.session_factory.begin() as session:
            await create_option(
                session,
                name_uz="uz",
                name_ru="ru",
                name_en="en",
                items=(),
            )
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(ContentOption.id))) == 0


async def test_option_and_item_pagination_normalize_out_of_range_pages(
    database: Database,
) -> None:
    for index in range(7):
        await make_option(database, str(index))
    async with database.session_factory() as session:
        first = await list_options(session, page=-5, page_size=5)
        last = await list_options(session, page=50, page_size=5)
        item_page = await list_option_items(
            session, option_id=first.items[0].id, page=99, page_size=1
        )
    assert (first.page, first.pages, len(first.items)) == (0, 2, 5)
    assert (last.page, len(last.items)) == (1, 2)
    assert (item_page.page, item_page.pages, item_page.total) == (0, 1, 1)


async def test_active_listing_excludes_inactive_and_empty_options(
    database: Database,
) -> None:
    active = await make_option(database, "active")
    inactive = await make_option(database, "inactive")
    empty = await make_option(database, "empty")
    async with database.session_factory.begin() as session:
        await set_option_active(session, inactive.id, False)
        only_item = (await get_option_items(session, empty.id))[0]
        await delete_option_item(session, only_item.id)
    async with database.session_factory() as session:
        result = await list_options(session, page=0, active_only=True)
    assert [option.id for option in result.items] == [active.id]


@pytest.mark.parametrize("language", list(Language))
async def test_update_each_option_name_language(database: Database, language: Language) -> None:
    option = await make_option(database, language.value)
    async with database.session_factory.begin() as session:
        updated = await update_option_name(session, option.id, language, " Updated ")
    assert updated is not None
    assert getattr(updated, f"name_{language.value}") == "Updated"


async def test_empty_option_cannot_be_enabled_and_new_item_does_not_auto_enable(
    database: Database,
) -> None:
    option = await make_option(database, "empty")
    async with database.session_factory.begin() as session:
        item = (await get_option_items(session, option.id))[0]
        await delete_option_item(session, item.id)
    with pytest.raises(EmptyOptionError):
        async with database.session_factory.begin() as session:
            await set_option_active(session, option.id, True)
    async with database.session_factory.begin() as session:
        added = await add_option_item(session, option.id, item_input("new"))
    async with database.session_factory() as session:
        stored = await get_option(session, option.id)
    assert added is not None
    assert stored is not None and not stored.is_active


async def test_deleting_option_cascades_all_content_items(database: Database) -> None:
    option = await make_option(database, "cascade", item_input("one"), item_input("two"))
    async with database.session_factory.begin() as session:
        assert await delete_option(session, option.id)
        assert not await delete_option(session, option.id)
    async with database.session_factory() as session:
        count = await session.scalar(
            select(func.count(OptionContentItem.id)).where(OptionContentItem.option_id == option.id)
        )
    assert count == 0


async def test_add_replace_and_edit_item_preserve_identity_and_order(
    database: Database,
) -> None:
    option = await make_option(database, "edit")
    async with database.session_factory.begin() as session:
        added = await add_option_item(session, option.id, item_input("photo", MediaType.PHOTO))
        assert added is not None
        item_id = added.id
        original_order = added.sort_order
        replaced = await replace_option_item(
            session, item_id, item_input("document", MediaType.DOCUMENT)
        )
        edited = await update_option_item_text(session, item_id, Language.RU, "Новый")
    assert replaced is not None and edited is not None
    assert replaced.id == item_id and replaced.sort_order == original_order
    assert replaced.media_type == MediaType.DOCUMENT
    assert edited.text_ru == "Новый"


async def test_deleting_final_item_deactivates_parent(database: Database) -> None:
    option = await make_option(database, "last")
    async with database.session_factory.begin() as session:
        item = (await get_option_items(session, option.id))[0]
        deleted, parent_id = await delete_option_item(session, item.id)
    async with database.session_factory() as session:
        stored = await get_option(session, option.id)
    assert (deleted, parent_id) == (True, option.id)
    assert stored is not None and not stored.is_active


async def test_deleting_missing_item_is_idempotent(database: Database) -> None:
    async with database.session_factory.begin() as session:
        assert await delete_option_item(session, 999999) == (False, None)


async def test_option_reordering_swaps_neighbors_and_reports_boundaries(
    database: Database,
) -> None:
    first = await make_option(database, "first")
    second = await make_option(database, "second")
    third = await make_option(database, "third")
    async with database.session_factory.begin() as session:
        assert not await move_option(session, first.id, -1)
        assert await move_option(session, third.id, -1)
        assert await move_option(session, first.id, 1)
    async with database.session_factory() as session:
        ordered = await list_options(session, page=0)
    assert [option.id for option in ordered.items] == [third.id, first.id, second.id]


async def test_item_reordering_is_scoped_to_its_parent(database: Database) -> None:
    first = await make_option(database, "first", item_input("a"), item_input("b"), item_input("c"))
    second = await make_option(database, "second", item_input("x"))
    async with database.session_factory.begin() as session:
        first_items = await get_option_items(session, first.id)
        assert await move_option_item(session, first_items[2].id, -1)
        assert not await move_option_item(session, first_items[0].id, -1)
    async with database.session_factory() as session:
        reordered = await get_option_items(session, first.id)
        untouched = await get_option_items(session, second.id)
    assert [item.text_en for item in reordered] == ["en-a", "en-c", "en-b"]
    assert [item.text_en for item in untouched] == ["en-x"]


async def test_item_reordering_normalizes_duplicate_legacy_sort_values(
    database: Database,
) -> None:
    option = await make_option(
        database,
        "duplicates",
        item_input("a"),
        item_input("b"),
        item_input("c"),
    )
    async with database.session_factory.begin() as session:
        items = await get_option_items(session, option.id)
        for current in items:
            current.sort_order = 10
    async with database.session_factory.begin() as session:
        items = await get_option_items(session, option.id)
        assert await move_option_item(session, items[0].id, 1)
    async with database.session_factory() as session:
        reordered = await get_option_items(session, option.id)
    assert [current.text_en for current in reordered] == ["en-b", "en-a", "en-c"]
    assert [current.sort_order for current in reordered] == [10, 20, 30]


@pytest.mark.parametrize("direction", [-99, 0, 99])
async def test_reordering_rejects_unknown_direction(database: Database, direction: int) -> None:
    option = await make_option(database, str(direction))
    async with database.session_factory.begin() as session:
        assert not await move_option(session, option.id, direction)


async def test_delivery_sends_mixed_items_in_order_and_continues_after_failure(
    database: Database,
) -> None:
    option = await make_option(
        database,
        "delivery",
        item_input("text", MediaType.TEXT),
        item_input("video", MediaType.VIDEO),
        item_input("photo", MediaType.PHOTO),
        item_input("document", MediaType.DOCUMENT),
    )
    async with database.session_factory() as session:
        items = await get_option_items(session, option.id)
    bot = AsyncMock()
    bot.send_video.side_effect = TelegramBadRequest(
        method=SendVideo(chat_id=42, video="file-video"),
        message="delivery failed",
    )
    report = await deliver_option_items(bot, 42, items, Language.RU)
    assert report == type(report)(total=4, sent=3, failed=1)
    bot.send_message.assert_awaited_once_with(42, "ru-text")
    bot.send_photo.assert_awaited_once_with(42, "file-photo", caption="ru-photo")
    bot.send_document.assert_awaited_once_with(42, "file-document", caption="ru-document")


async def test_missing_crud_targets_return_false_or_none(database: Database) -> None:
    async with database.session_factory.begin() as session:
        assert await get_option(session, 999) is None
        assert await get_option_item(session, 999) is None
        assert await add_option_item(session, 999, item_input("missing")) is None
        assert await replace_option_item(session, 999, item_input("missing")) is None
        assert await update_option_item_text(session, 999, Language.EN, "missing") is None
        assert not await set_option_active(session, 999, False)
        assert not await move_option(session, 999, 1)
        assert not await move_option_item(session, 999, 1)
