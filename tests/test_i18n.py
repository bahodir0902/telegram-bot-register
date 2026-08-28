from string import Formatter

from app.bot.keyboards.user import (
    contact_keyboard,
    language_keyboard,
    language_selector_keyboard,
)
from app.i18n import LANGUAGE_BUTTON_TEXT, TRANSLATIONS, Language, tr


def test_translation_catalogs_have_identical_keys() -> None:
    expected = set(TRANSLATIONS[Language.UZ])
    assert expected
    assert all(set(catalog) == expected for catalog in TRANSLATIONS.values())
    for key in expected:
        placeholders = {
            language: {
                field_name
                for _, field_name, _, _ in Formatter().parse(catalog[key])
                if field_name is not None
            }
            for language, catalog in TRANSLATIONS.items()
        }
        assert len({frozenset(fields) for fields in placeholders.values()}) == 1


def test_representative_text_and_keyboards_render_in_every_language() -> None:
    for language in Language:
        assert tr(language, "welcome")
        keyboard = contact_keyboard(language)
        assert keyboard.keyboard[0][0].text == tr(language, "share_phone")
        assert keyboard.keyboard[1][0].text == LANGUAGE_BUTTON_TEXT

    for language in Language:
        persistent = language_keyboard(language)
        assert persistent.is_persistent
        assert persistent.keyboard[0][0].text == LANGUAGE_BUTTON_TEXT
        assert persistent.keyboard[1][0].text == tr(language, "show_options")
    assert len(language_selector_keyboard().inline_keyboard[0]) == 3
