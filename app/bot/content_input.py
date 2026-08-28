from __future__ import annotations

from aiogram.types import Message

from app.db.models import MediaType
from app.i18n import Language, tr
from app.services.content import (
    CAPTION_LIMIT,
    TEXT_LIMIT,
    validate_content_text,
)
from app.services.options import OptionItemInput


def content_validation_text(
    value: str | None, media_type: MediaType, language: Language
) -> str | None:
    try:
        validate_content_text(value, media_type)
    except ValueError:
        if value is None or not value.strip():
            return tr(language, "content_empty")
        limit = TEXT_LIMIT if media_type == MediaType.TEXT else CAPTION_LIMIT
        return tr(language, "content_too_long", limit=limit)
    return None


def extract_content(message: Message) -> tuple[dict[str, str | None], str | None] | None:
    if message.text is not None:
        return (
            {
                "media_type": MediaType.TEXT.value,
                "telegram_file_id": "",
                "telegram_file_unique_id": None,
                "original_filename": None,
            },
            message.text,
        )
    if message.video is not None:
        return (
            {
                "media_type": MediaType.VIDEO.value,
                "telegram_file_id": message.video.file_id,
                "telegram_file_unique_id": message.video.file_unique_id,
                "original_filename": (message.video.file_name or "")[:255] or None,
            },
            message.caption,
        )
    if message.photo:
        photo = message.photo[-1]
        return (
            {
                "media_type": MediaType.PHOTO.value,
                "telegram_file_id": photo.file_id,
                "telegram_file_unique_id": photo.file_unique_id,
                "original_filename": None,
            },
            message.caption,
        )
    if message.document is not None:
        return (
            {
                "media_type": MediaType.DOCUMENT.value,
                "telegram_file_id": message.document.file_id,
                "telegram_file_unique_id": message.document.file_unique_id,
                "original_filename": (message.document.file_name or "")[:255] or None,
            },
            message.caption,
        )
    return None


def option_item_input(data: dict[str, object]) -> OptionItemInput:
    return OptionItemInput(
        media_type=MediaType(str(data["media_type"])),
        telegram_file_id=str(data.get("telegram_file_id") or ""),
        telegram_file_unique_id=(
            str(data["telegram_file_unique_id"])
            if data.get("telegram_file_unique_id") is not None
            else None
        ),
        original_filename=(
            str(data["original_filename"]) if data.get("original_filename") is not None else None
        ),
        text_uz=str(data["text_uz"]),
        text_ru=str(data["text_ru"]),
        text_en=str(data["text_en"]),
    )


def option_item_inputs(data: dict[str, object]) -> tuple[OptionItemInput, ...]:
    raw_payloads = data.get("content_payloads")
    if not isinstance(raw_payloads, list) or not raw_payloads:
        return (option_item_input(data),)
    items: list[OptionItemInput] = []
    for raw_payload in raw_payloads:
        if not isinstance(raw_payload, dict):
            raise ValueError("invalid content payload")
        payload = {
            **raw_payload,
            "text_uz": data["text_uz"],
            "text_ru": data["text_ru"],
            "text_en": data["text_en"],
        }
        items.append(option_item_input(payload))
    return tuple(items)
