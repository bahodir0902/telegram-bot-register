from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from aiogram.types import Chat, Message, User, Video

from app.bot.albums import AlbumCollector


def video_message(message_id: int, group_id: str | None) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=10, type="private"),
        from_user=User(id=10, is_bot=False, first_name="Admin"),
        video=Video(
            file_id=f"file-{message_id}",
            file_unique_id=f"unique-{message_id}",
            width=100,
            height=100,
            duration=1,
        ),
        media_group_id=group_id,
    )


async def test_non_album_message_is_released_immediately() -> None:
    collector = AlbumCollector(debounce_seconds=1)
    message = video_message(1, None)
    assert await collector.collect(message) == (message,)


async def test_album_is_released_once_in_message_order() -> None:
    collector = AlbumCollector(debounce_seconds=0.01)
    second = video_message(2, "group")
    first = video_message(1, "group")
    results = await asyncio.gather(
        collector.collect(second),
        collector.collect(first),
    )
    bundles = [result for result in results if result is not None]
    assert len(bundles) == 1
    assert [message.message_id for message in bundles[0]] == [1, 2]


async def test_separate_albums_do_not_mix() -> None:
    collector = AlbumCollector(debounce_seconds=0.01)
    results = await asyncio.gather(
        collector.collect(video_message(1, "first")),
        collector.collect(video_message(2, "first")),
        collector.collect(video_message(3, "second")),
        collector.collect(video_message(4, "second")),
    )
    bundles = [result for result in results if result is not None]
    assert [[message.message_id for message in bundle] for bundle in bundles] == [
        [1, 2],
        [3, 4],
    ]


async def test_late_member_of_completed_album_is_ignored() -> None:
    collector = AlbumCollector(debounce_seconds=0.01)
    first = video_message(1, "group")
    assert await collector.collect(first) == (first,)
    assert await collector.collect(video_message(2, "group")) is None


async def test_duplicate_album_update_is_released_to_only_one_caller() -> None:
    collector = AlbumCollector(debounce_seconds=0.01)
    first_delivery = video_message(1, "group")
    duplicate_delivery = video_message(1, "group")
    results = await asyncio.gather(
        collector.collect(first_delivery),
        collector.collect(duplicate_delivery),
    )
    assert sum(result is not None for result in results) == 1
