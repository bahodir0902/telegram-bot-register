from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import func, select, update

from app.db.models import (
    Broadcast,
    BroadcastRecipient,
    BroadcastRecipientStatus,
    BroadcastStatus,
    MediaType,
)
from app.db.session import Database
from app.i18n import Language
from app.services.broadcasts import (
    BroadcastWorker,
    cancel_broadcast,
    create_broadcast,
    get_broadcast_progress,
    recover_interrupted_broadcasts,
)
from app.services.users import (
    get_user,
    mark_user_unreachable,
    set_user_language,
    upsert_user,
)


async def add_user(
    database: Database, telegram_id: int, language: Language, *, reachable: bool = True
) -> None:
    async with database.session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=telegram_id,
            username=None,
            first_name=f"User {telegram_id}",
            last_name=None,
        )
        await set_user_language(session, telegram_id, language)
        if not reachable:
            await mark_user_unreachable(session, telegram_id)


async def queue_text_broadcast(
    database: Database, *, token: str = "request-1", admin_id: int = 10
) -> Broadcast:
    async with database.session_factory.begin() as session:
        broadcast, _created = await create_broadcast(
            session,
            request_token=token,
            admin_telegram_id=admin_id,
            admin_language=Language.EN,
            media_type=MediaType.TEXT,
            telegram_file_id="",
            telegram_file_unique_id=None,
            original_filename=None,
            text_uz="Salom",
            text_ru="Привет",
            text_en="Hello",
        )
        return broadcast


async def test_audience_is_snapshotted_once_and_excludes_unreachable_users(
    database: Database,
) -> None:
    await add_user(database, 1, Language.UZ)
    await add_user(database, 2, Language.RU)
    await add_user(database, 3, Language.EN, reachable=False)

    broadcast = await queue_text_broadcast(database)
    await add_user(database, 4, Language.EN)

    async with database.session_factory.begin() as session:
        duplicate, created = await create_broadcast(
            session,
            request_token="request-1",
            admin_telegram_id=10,
            admin_language=Language.EN,
            media_type=MediaType.TEXT,
            telegram_file_id="",
            telegram_file_unique_id=None,
            original_filename=None,
            text_uz="ignored",
            text_ru="ignored",
            text_en="ignored",
        )
        recipients = (
            await session.scalars(
                select(BroadcastRecipient)
                .where(BroadcastRecipient.broadcast_id == broadcast.id)
                .order_by(BroadcastRecipient.telegram_id)
            )
        ).all()

    assert not created
    assert duplicate.id == broadcast.id
    assert [(item.telegram_id, item.language_code) for item in recipients] == [
        (1, Language.UZ),
        (2, Language.RU),
    ]


async def test_worker_uses_snapshot_language_and_isolates_blocked_user(
    database: Database,
) -> None:
    for telegram_id, language in (
        (1, Language.UZ),
        (2, Language.RU),
        (3, Language.EN),
    ):
        await add_user(database, telegram_id, language)
    broadcast = await queue_text_broadcast(database)
    calls: list[tuple[int, str]] = []

    async def send_message(chat_id: int, text: str, **_kwargs) -> None:
        calls.append((chat_id, text))
        if chat_id == 2:
            raise TelegramForbiddenError(
                method=SendMessage(chat_id=chat_id, text=text),
                message="bot was blocked by the user",
            )

    worker = BroadcastWorker(SimpleNamespace(send_message=send_message), database.session_factory)
    for _ in range(3):
        assert await worker._process_next()

    async with database.session_factory() as session:
        progress = await get_broadcast_progress(session, broadcast.id)
        blocked = await get_user(session, 2)

    assert calls == [(1, "Salom"), (2, "Привет"), (3, "Hello")]
    assert progress is not None
    assert progress.broadcast.status == BroadcastStatus.COMPLETED
    assert (progress.sent, progress.failed) == (2, 1)
    assert blocked is not None and not blocked.is_reachable


async def test_retry_after_is_persisted_then_retried(database: Database) -> None:
    await add_user(database, 1, Language.EN)
    broadcast = await queue_text_broadcast(database)
    call_count = 0

    async def send_message(chat_id: int, text: str, **_kwargs) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TelegramRetryAfter(
                method=SendMessage(chat_id=chat_id, text=text),
                message="too many requests",
                retry_after=1,
            )

    worker = BroadcastWorker(SimpleNamespace(send_message=send_message), database.session_factory)
    assert await worker._process_next()

    async with database.session_factory.begin() as session:
        recipient = await session.scalar(
            select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast.id)
        )
        assert recipient is not None
        assert recipient.status == BroadcastRecipientStatus.PENDING
        assert recipient.attempt_count == 1
        recipient.next_attempt_at = None

    assert await worker._process_next()
    async with database.session_factory() as session:
        progress = await get_broadcast_progress(session, broadcast.id)
    assert call_count == 2
    assert progress is not None
    assert progress.sent == 1
    assert progress.broadcast.status == BroadcastStatus.COMPLETED


async def test_cancellation_keeps_sent_and_cancels_only_pending(
    database: Database,
) -> None:
    await add_user(database, 1, Language.EN)
    await add_user(database, 2, Language.EN)
    broadcast = await queue_text_broadcast(database)

    async def send_message(*_args, **_kwargs) -> None:
        pass

    worker = BroadcastWorker(SimpleNamespace(send_message=send_message), database.session_factory)
    assert await worker._process_next()
    async with database.session_factory.begin() as session:
        assert await cancel_broadcast(session, broadcast.id)

    async with database.session_factory() as session:
        progress = await get_broadcast_progress(session, broadcast.id)
    assert progress is not None
    assert progress.broadcast.status == BroadcastStatus.CANCELLED
    assert (progress.sent, progress.cancelled) == (1, 1)


async def test_recovery_requeues_claimed_recipient(database: Database) -> None:
    await add_user(database, 1, Language.EN)
    broadcast = await queue_text_broadcast(database)
    async with database.session_factory.begin() as session:
        await session.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast.id)
            .values(status=BroadcastStatus.RUNNING)
        )
        await session.execute(
            update(BroadcastRecipient)
            .where(BroadcastRecipient.broadcast_id == broadcast.id)
            .values(status=BroadcastRecipientStatus.SENDING)
        )

    async with database.session_factory.begin() as session:
        await recover_interrupted_broadcasts(session)
    async with database.session_factory() as session:
        status = await session.scalar(
            select(BroadcastRecipient.status).where(BroadcastRecipient.broadcast_id == broadcast.id)
        )
    assert status == BroadcastRecipientStatus.PENDING


async def test_fifo_worker_does_not_start_second_broadcast_early(
    database: Database,
) -> None:
    await add_user(database, 1, Language.EN)
    first = await queue_text_broadcast(database, token="first")
    second = await queue_text_broadcast(database, token="second")

    async def send_message(*_args, **_kwargs) -> None:
        pass

    worker = BroadcastWorker(SimpleNamespace(send_message=send_message), database.session_factory)
    assert await worker._process_next()

    async with database.session_factory() as session:
        first_status = await session.scalar(
            select(Broadcast.status).where(Broadcast.id == first.id)
        )
        second_status = await session.scalar(
            select(Broadcast.status).where(Broadcast.id == second.id)
        )
        second_attempts = await session.scalar(
            select(func.sum(BroadcastRecipient.attempt_count)).where(
                BroadcastRecipient.broadcast_id == second.id
            )
        )
    assert first_status == BroadcastStatus.COMPLETED
    assert second_status == BroadcastStatus.QUEUED
    assert second_attempts == 0


async def test_background_worker_starts_and_stops_cleanly(database: Database) -> None:
    await add_user(database, 1, Language.EN)
    broadcast = await queue_text_broadcast(database)
    sent = asyncio.Event()

    async def send_message(*_args, **_kwargs) -> None:
        sent.set()

    worker = BroadcastWorker(SimpleNamespace(send_message=send_message), database.session_factory)
    await worker.start()
    try:
        worker.wake()
        await asyncio.wait_for(sent.wait(), timeout=2)
        for _ in range(20):
            async with database.session_factory() as session:
                progress = await get_broadcast_progress(session, broadcast.id)
            if progress is not None and progress.broadcast.status == BroadcastStatus.COMPLETED:
                break
            await asyncio.sleep(0.05)
        assert progress is not None
        assert progress.broadcast.status == BroadcastStatus.COMPLETED
    finally:
        await worker.stop()
