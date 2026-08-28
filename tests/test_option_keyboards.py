from __future__ import annotations

import pytest

from app.bot.keyboards.admin import (
    option_delete_keyboard,
    option_detail_keyboard,
    option_item_delete_keyboard,
    option_item_detail_keyboard,
    option_items_keyboard,
    option_list_keyboard,
)
from app.bot.keyboards.user import options_keyboard
from app.db.models import ContentOption, MediaType, OptionContentItem
from app.i18n import Language
from app.services.options import OptionItemPage, OptionPage


def option(*, option_id: int = 1, active: bool = True) -> ContentOption:
    return ContentOption(
        id=option_id,
        name_uz="O‘zbekcha",
        name_ru="Русский",
        name_en="English",
        is_active=active,
        sort_order=10,
    )


def item(*, item_id: int = 1, option_id: int = 1) -> OptionContentItem:
    return OptionContentItem(
        id=item_id,
        option_id=option_id,
        media_type=MediaType.TEXT,
        telegram_file_id="",
        text_uz="Uzbek text",
        text_ru="Russian text",
        text_en="English text",
        sort_order=10,
    )


def callback_values(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (Language.UZ, "O‘zbekcha"),
        (Language.RU, "Русский"),
        (Language.EN, "English"),
    ],
)
def test_user_option_button_uses_selected_language(language: Language, expected: str) -> None:
    markup = options_keyboard(OptionPage((option(),), 0, 1, 1), language)
    assert markup.inline_keyboard[0][0].text == expected
    assert markup.inline_keyboard[0][0].callback_data == "choice:select:1:0"


@pytest.mark.parametrize(
    ("page", "pages", "expected_actions"),
    [
        (0, 1, []),
        (0, 3, ["choice:page:0:1"]),
        (1, 3, ["choice:page:0:0", "choice:page:0:2"]),
        (2, 3, ["choice:page:0:1"]),
    ],
)
def test_user_option_pagination_has_only_valid_neighbors(
    page: int, pages: int, expected_actions: list[str]
) -> None:
    markup = options_keyboard(OptionPage((option(),), page, pages, 20), Language.EN)
    assert callback_values(markup)[1:] == expected_actions


def test_admin_option_list_marks_active_state_and_has_navigation() -> None:
    active = option(option_id=1)
    inactive = option(option_id=2, active=False)
    result = OptionPage((active, inactive), 1, 3, 12)
    markup = option_list_keyboard(result, Language.EN)
    assert markup.inline_keyboard[0][0].text.startswith("🟢")
    assert markup.inline_keyboard[1][0].text.startswith("🔴")
    callbacks = callback_values(markup)
    assert "option:page:0:0" in callbacks
    assert "option:page:0:2" in callbacks


def test_item_label_truncation_never_expands_admin_button_unbounded() -> None:
    long_item = item()
    long_item.text_uz = "first line\n" + "x" * 100
    result = OptionItemPage((long_item,), 0, 1, 1)
    markup = option_items_keyboard(option(), result, 0, Language.UZ)
    assert "\n" not in markup.inline_keyboard[0][0].text
    assert len(markup.inline_keyboard[0][0].text) <= 42


def test_all_option_admin_keyboards_keep_callback_data_within_telegram_limit() -> None:
    large_id = 2_147_483_647
    large_page = 999_999
    selected_option = option(option_id=large_id)
    selected_item = item(item_id=large_id, option_id=large_id)
    option_page = OptionPage((selected_option,), large_page, large_page + 2, large_id)
    item_page = OptionItemPage((selected_item,), large_page, large_page + 2, large_id)
    markups = [
        option_list_keyboard(option_page, Language.EN),
        option_detail_keyboard(selected_option, large_page, Language.EN),
        option_delete_keyboard(selected_option, large_page, Language.EN),
        option_items_keyboard(selected_option, item_page, large_page, Language.EN),
        option_item_detail_keyboard(selected_item, large_page, large_page, Language.EN),
        option_item_delete_keyboard(selected_item, large_page, large_page, Language.EN),
    ]
    callbacks = [value for markup in markups for value in callback_values(markup)]
    assert callbacks
    assert max(len(value.encode()) for value in callbacks) <= 64
