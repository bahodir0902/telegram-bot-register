from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.bot.content_input import (
    content_validation_text,
    extract_content,
    option_item_input,
    option_item_inputs,
)
from app.db.models import MediaType
from app.i18n import Language


def message(**overrides):
    values = {"text": None, "video": None, "photo": None, "document": None, "caption": None}
    values.update(overrides)
    return SimpleNamespace(**values)


def file(file_id: str, *, unique_id: str = "unique", file_name: str | None = None):
    return SimpleNamespace(
        file_id=file_id,
        file_unique_id=unique_id,
        file_name=file_name,
    )


def test_extract_plain_text_content() -> None:
    payload, initial_text = extract_content(message(text="Hello"))
    assert payload == {
        "media_type": "text",
        "telegram_file_id": "",
        "telegram_file_unique_id": None,
        "original_filename": None,
    }
    assert initial_text == "Hello"


@pytest.mark.parametrize(
    ("field", "media_type"),
    [("video", "video"), ("document", "document")],
)
def test_extract_named_telegram_file(field: str, media_type: str) -> None:
    content = file("file-id", unique_id="unique-id", file_name="medical.bin")
    payload, initial_text = extract_content(
        message(**{field: content}, caption="Localized caption")
    )
    assert payload == {
        "media_type": media_type,
        "telegram_file_id": "file-id",
        "telegram_file_unique_id": "unique-id",
        "original_filename": "medical.bin",
    }
    assert initial_text == "Localized caption"


def test_extract_photo_uses_largest_telegram_variant() -> None:
    payload, initial_text = extract_content(
        message(photo=[file("small"), file("large", unique_id="large-unique")], caption="Photo")
    )
    assert payload["media_type"] == "photo"
    assert payload["telegram_file_id"] == "large"
    assert payload["telegram_file_unique_id"] == "large-unique"
    assert payload["original_filename"] is None
    assert initial_text == "Photo"


def test_extract_media_without_caption_requests_uzbek_text_later() -> None:
    _payload, initial_text = extract_content(message(video=file("video")))
    assert initial_text is None


def test_extract_filename_is_bounded_for_database_column() -> None:
    payload, _ = extract_content(message(document=file("doc", file_name="x" * 300)))
    assert len(payload["original_filename"]) == 255


@pytest.mark.parametrize(
    "unsupported",
    [
        message(),
        message(photo=[]),
        message(text=None, caption="caption without media"),
    ],
)
def test_extract_unsupported_input_returns_none(unsupported) -> None:
    assert extract_content(unsupported) is None


@pytest.mark.parametrize("language", list(Language))
def test_content_validation_error_is_localized_for_empty_text(language: Language) -> None:
    error = content_validation_text(" ", MediaType.TEXT, language)
    assert error and "4096" not in error


@pytest.mark.parametrize(
    ("media_type", "length", "shown_limit"),
    [
        (MediaType.TEXT, 4097, "4096"),
        (MediaType.PHOTO, 1025, "1024"),
        (MediaType.VIDEO, 1025, "1024"),
        (MediaType.DOCUMENT, 1025, "1024"),
    ],
)
def test_content_validation_reports_type_specific_limit(
    media_type: MediaType, length: int, shown_limit: str
) -> None:
    assert shown_limit in content_validation_text("x" * length, media_type, Language.EN)


def test_content_validation_accepts_valid_value() -> None:
    assert content_validation_text("valid", MediaType.TEXT, Language.EN) is None


def test_option_item_input_normalizes_serialized_fsm_payload() -> None:
    result = option_item_input(
        {
            "media_type": "photo",
            "telegram_file_id": "file",
            "telegram_file_unique_id": None,
            "original_filename": None,
            "text_uz": "uz",
            "text_ru": "ru",
            "text_en": "en",
        }
    )
    assert result.media_type is MediaType.PHOTO
    assert result.telegram_file_id == "file"
    assert result.telegram_file_unique_id is None


def test_option_item_inputs_expands_album_payloads_with_shared_translations() -> None:
    items = option_item_inputs(
        {
            "content_payloads": [
                {
                    "media_type": "video",
                    "telegram_file_id": "one",
                    "telegram_file_unique_id": "unique-one",
                    "original_filename": None,
                },
                {
                    "media_type": "video",
                    "telegram_file_id": "two",
                    "telegram_file_unique_id": "unique-two",
                    "original_filename": None,
                },
            ],
            "text_uz": "uz",
            "text_ru": "ru",
            "text_en": "en",
        }
    )
    assert [item.telegram_file_id for item in items] == ["one", "two"]
    assert all(item.text_uz == "uz" and item.text_ru == "ru" for item in items)


@pytest.mark.parametrize("content_payloads", [[], [None], "invalid"])
def test_option_item_inputs_rejects_invalid_album_payloads(content_payloads) -> None:
    data = {
        "content_payloads": content_payloads,
        "text_uz": "uz",
        "text_ru": "ru",
        "text_en": "en",
    }
    with pytest.raises((KeyError, ValueError)):
        option_item_inputs(data)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"media_type": "audio", "text_uz": "uz", "text_ru": "ru", "text_en": "en"},
        {"media_type": "text", "text_uz": "uz", "text_ru": "ru"},
    ],
)
def test_option_item_input_rejects_incomplete_or_unknown_payload(payload) -> None:
    with pytest.raises((KeyError, ValueError)):
        option_item_input(payload)
