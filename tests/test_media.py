from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendVideo

from app.db.models import MediaType
from app.db.session import Database
from app.i18n import Language
from app.services.media import (
    CAPTION_LIMIT,
    TEXT_LIMIT,
    ContentValidationError,
    add_media,
    delete_media,
    deliver_active_media,
    get_active_media,
    get_media,
    set_media_active,
    validate_content_text,
)


async def add_test_media(
    database: Database,
    media_type: MediaType,
    file_id: str,
):
    async with database.session_factory.begin() as session:
        return await add_media(
            session,
            telegram_file_id=file_id,
            telegram_file_unique_id=f"unique-{file_id}",
            media_type=media_type,
            original_filename=f"{file_id}.bin",
            caption=f"Caption {file_id}",
        )


async def test_active_media_order_activation_and_deletion(database: Database) -> None:
    first = await add_test_media(database, MediaType.VIDEO, "video-1")
    second = await add_test_media(database, MediaType.PHOTO, "photo-1")

    assert (first.sort_order, second.sort_order) == (10, 20)

    async with database.session_factory.begin() as session:
        assert await set_media_active(session, first.id, False)
    async with database.session_factory() as session:
        active = await get_active_media(session)
    assert [item.id for item in active] == [second.id]

    async with database.session_factory.begin() as session:
        assert await delete_media(session, second.id)
        assert not await delete_media(session, second.id)
    async with database.session_factory() as session:
        assert await get_media(session, second.id) is None


async def test_delivery_uses_correct_methods_and_continues_after_failure(
    database: Database,
) -> None:
    await add_test_media(database, MediaType.VIDEO, "video-1")
    await add_test_media(database, MediaType.PHOTO, "photo-1")
    await add_test_media(database, MediaType.DOCUMENT, "document-1")

    bot = AsyncMock()
    bot.send_video.side_effect = TelegramBadRequest(
        method=SendVideo(chat_id=42, video="video-1"),
        message="delivery failed",
    )

    report = await deliver_active_media(bot, 42, database.session_factory)

    assert (report.total, report.sent, report.failed) == (3, 2, 1)
    bot.send_video.assert_awaited_once()
    bot.send_photo.assert_awaited_once_with(42, "photo-1", caption="Caption photo-1")
    bot.send_document.assert_awaited_once_with(42, "document-1", caption="Caption document-1")


async def test_text_and_media_share_order_and_use_recipient_language(
    database: Database,
) -> None:
    async with database.session_factory.begin() as session:
        text_item = await add_media(
            session,
            telegram_file_id="",
            telegram_file_unique_id=None,
            media_type=MediaType.TEXT,
            original_filename=None,
            caption="O‘zbekcha",
            text_uz="O‘zbekcha",
            text_ru="Русский <текст>",
            text_en="English",
        )
        photo_item = await add_media(
            session,
            telegram_file_id="photo-id",
            telegram_file_unique_id="photo-unique",
            media_type=MediaType.PHOTO,
            original_filename=None,
            caption="Izoh",
            text_uz="Izoh",
            text_ru="Подпись",
            text_en="Caption",
        )

    bot = AsyncMock()
    report = await deliver_active_media(bot, 42, database.session_factory, language=Language.RU)

    assert (text_item.sort_order, photo_item.sort_order) == (10, 20)
    assert (report.total, report.sent, report.failed) == (2, 2, 0)
    bot.send_message.assert_awaited_once_with(42, "Русский &lt;текст&gt;")
    bot.send_photo.assert_awaited_once_with(42, "photo-id", caption="Подпись")


def test_content_validation_enforces_telegram_limits() -> None:
    assert validate_content_text("x" * TEXT_LIMIT, MediaType.TEXT)
    assert validate_content_text("x" * CAPTION_LIMIT, MediaType.PHOTO)
    with pytest.raises(ContentValidationError):
        validate_content_text(" ", MediaType.TEXT)
    with pytest.raises(ContentValidationError):
        validate_content_text("x" * (TEXT_LIMIT + 1), MediaType.TEXT)
    with pytest.raises(ContentValidationError):
        validate_content_text("x" * (CAPTION_LIMIT + 1), MediaType.VIDEO)
