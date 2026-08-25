from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Broadcast,
    BroadcastRecipient,
    BroadcastRecipientStatus,
    BroadcastStatus,
    MediaType,
    User,
)
from app.db.session import AsyncSessionFactory
from app.i18n import DEFAULT_LANGUAGE, Language
from app.services.media import localized_content_text, send_content
from app.services.users import mark_user_unreachable

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
SEND_INTERVAL_SECONDS = 0.05
WORKER_IDLE_SECONDS = 1.0
MAX_ERROR_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class BroadcastProgress:
    broadcast: Broadcast
    total: int
    pending: int
    sending: int
    sent: int
    failed: int
    cancelled: int


async def create_broadcast(
    session: AsyncSession,
    *,
    request_token: str,
    admin_telegram_id: int,
    admin_language: Language,
    media_type: MediaType,
    telegram_file_id: str,
    telegram_file_unique_id: str | None,
    original_filename: str | None,
    text_uz: str,
    text_ru: str,
    text_en: str,
) -> tuple[Broadcast, bool]:
    """Persist one broadcast and its immutable audience snapshot atomically."""

    now = datetime.now(UTC)
    statement = (
        sqlite_insert(Broadcast)
        .values(
            request_token=request_token,
            admin_telegram_id=admin_telegram_id,
            admin_language=admin_language,
            media_type=media_type,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            original_filename=original_filename,
            text_uz=text_uz,
            text_ru=text_ru,
            text_en=text_en,
            status=BroadcastStatus.QUEUED,
            cancellation_requested=False,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=[Broadcast.request_token])
        .returning(Broadcast.id)
    )
    broadcast_id = (await session.execute(statement)).scalar_one_or_none()
    if broadcast_id is None:
        existing = await session.scalar(
            select(Broadcast).where(Broadcast.request_token == request_token)
        )
        if existing is None:  # pragma: no cover - defensive database boundary
            raise RuntimeError("broadcast confirmation could not be resolved")
        return existing, False

    broadcast = await session.get(Broadcast, int(broadcast_id))
    if broadcast is None:  # pragma: no cover - defensive database boundary
        raise RuntimeError("created broadcast could not be loaded")

    audience = (
        await session.execute(
            select(User.telegram_id, User.language_code)
            .where(User.is_reachable.is_(True))
            .order_by(User.id.asc())
        )
    ).all()
    session.add_all(
        BroadcastRecipient(
            broadcast_id=broadcast.id,
            telegram_id=telegram_id,
            language_code=language_code or DEFAULT_LANGUAGE,
            status=BroadcastRecipientStatus.PENDING,
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        for telegram_id, language_code in audience
    )
    if not audience:
        broadcast.status = BroadcastStatus.COMPLETED
        broadcast.finished_at = now
    await session.flush()
    return broadcast, True


async def get_broadcast(session: AsyncSession, broadcast_id: int) -> Broadcast | None:
    return await session.get(Broadcast, broadcast_id)


async def get_broadcast_progress(
    session: AsyncSession, broadcast_id: int
) -> BroadcastProgress | None:
    broadcast = await get_broadcast(session, broadcast_id)
    if broadcast is None:
        return None
    rows = (
        await session.execute(
            select(BroadcastRecipient.status, func.count(BroadcastRecipient.id))
            .where(BroadcastRecipient.broadcast_id == broadcast_id)
            .group_by(BroadcastRecipient.status)
        )
    ).all()
    counts = {status: int(count) for status, count in rows}
    return BroadcastProgress(
        broadcast=broadcast,
        total=sum(counts.values()),
        pending=counts.get(BroadcastRecipientStatus.PENDING, 0),
        sending=counts.get(BroadcastRecipientStatus.SENDING, 0),
        sent=counts.get(BroadcastRecipientStatus.SENT, 0),
        failed=counts.get(BroadcastRecipientStatus.FAILED, 0),
        cancelled=counts.get(BroadcastRecipientStatus.CANCELLED, 0),
    )


async def cancel_broadcast(session: AsyncSession, broadcast_id: int) -> bool:
    broadcast = await get_broadcast(session, broadcast_id)
    if broadcast is None or broadcast.status in {
        BroadcastStatus.COMPLETED,
        BroadcastStatus.CANCELLED,
    }:
        return False
    broadcast.cancellation_requested = True
    await session.execute(
        update(BroadcastRecipient)
        .where(
            BroadcastRecipient.broadcast_id == broadcast_id,
            BroadcastRecipient.status == BroadcastRecipientStatus.PENDING,
        )
        .values(
            status=BroadcastRecipientStatus.CANCELLED,
            updated_at=datetime.now(UTC),
        )
    )
    await _finalize_broadcast(session, broadcast)
    return True


async def recover_interrupted_broadcasts(session: AsyncSession) -> None:
    """Return recipients claimed before a process stop to the durable queue."""

    await session.execute(
        update(BroadcastRecipient)
        .where(BroadcastRecipient.status == BroadcastRecipientStatus.SENDING)
        .values(
            status=BroadcastRecipientStatus.PENDING,
            next_attempt_at=None,
            updated_at=datetime.now(UTC),
        )
    )


async def _finalize_broadcast(session: AsyncSession, broadcast: Broadcast) -> bool:
    remaining = int(
        await session.scalar(
            select(func.count(BroadcastRecipient.id)).where(
                BroadcastRecipient.broadcast_id == broadcast.id,
                BroadcastRecipient.status.in_(
                    [
                        BroadcastRecipientStatus.PENDING,
                        BroadcastRecipientStatus.SENDING,
                    ]
                ),
            )
        )
        or 0
    )
    if remaining:
        return False
    broadcast.status = (
        BroadcastStatus.CANCELLED if broadcast.cancellation_requested else BroadcastStatus.COMPLETED
    )
    broadcast.finished_at = datetime.now(UTC)
    return True


def _is_permanently_unreachable(error: TelegramAPIError) -> bool:
    if isinstance(error, (TelegramForbiddenError, TelegramNotFound)):
        return True
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "bot was blocked",
            "chat not found",
            "user is deactivated",
            "can't initiate conversation",
            "cannot initiate conversation",
        )
    )


class BroadcastWorker:
    """Single-process, durable FIFO worker for Telegram broadcasts."""

    def __init__(self, bot: Bot, session_factory: AsyncSessionFactory) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        async with self.session_factory.begin() as session:
            await recover_interrupted_broadcasts(session)
        self._task = asyncio.create_task(self._run(), name="broadcast-worker")

    def wake(self) -> None:
        self._wake_event.set()

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._stop_event.set()
        self._wake_event.set()
        try:
            await asyncio.wait_for(task, timeout=10)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                worked = await self._process_next()
            except Exception:
                worked = False
                logger.exception("Broadcast worker iteration failed")
            if worked:
                continue
            self._wake_event.clear()
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=WORKER_IDLE_SECONDS)
            except TimeoutError:
                pass

    async def _process_next(self) -> bool:
        async with self.session_factory.begin() as session:
            broadcast = await session.scalar(
                select(Broadcast)
                .where(Broadcast.status.in_([BroadcastStatus.QUEUED, BroadcastStatus.RUNNING]))
                .order_by(Broadcast.id.asc())
                .limit(1)
            )
            if broadcast is None:
                return False
            if broadcast.status == BroadcastStatus.QUEUED:
                broadcast.status = BroadcastStatus.RUNNING
                broadcast.started_at = datetime.now(UTC)
            if broadcast.cancellation_requested:
                await session.execute(
                    update(BroadcastRecipient)
                    .where(
                        BroadcastRecipient.broadcast_id == broadcast.id,
                        BroadcastRecipient.status == BroadcastRecipientStatus.PENDING,
                    )
                    .values(
                        status=BroadcastRecipientStatus.CANCELLED,
                        updated_at=datetime.now(UTC),
                    )
                )
                await _finalize_broadcast(session, broadcast)
                return True

            recipient = await session.scalar(
                select(BroadcastRecipient)
                .where(
                    BroadcastRecipient.broadcast_id == broadcast.id,
                    BroadcastRecipient.status == BroadcastRecipientStatus.PENDING,
                    or_(
                        BroadcastRecipient.next_attempt_at.is_(None),
                        BroadcastRecipient.next_attempt_at <= datetime.now(UTC),
                    ),
                )
                .order_by(BroadcastRecipient.id.asc())
                .limit(1)
            )
            if recipient is None:
                await _finalize_broadcast(session, broadcast)
                return False
            claimed = await session.execute(
                update(BroadcastRecipient)
                .where(
                    BroadcastRecipient.id == recipient.id,
                    BroadcastRecipient.status == BroadcastRecipientStatus.PENDING,
                )
                .values(
                    status=BroadcastRecipientStatus.SENDING,
                    updated_at=datetime.now(UTC),
                )
            )
            if claimed.rowcount != 1:
                return True
            recipient_id = recipient.id
            broadcast_id = broadcast.id
            telegram_id = recipient.telegram_id
            language = recipient.language_code
            media_type = broadcast.media_type
            telegram_file_id = broadcast.telegram_file_id
            text = localized_content_text(broadcast, language)
            previous_attempts = recipient.attempt_count

        try:
            await send_content(
                self.bot,
                telegram_id,
                media_type=media_type,
                telegram_file_id=telegram_file_id,
                text=text,
            )
        except TelegramRetryAfter as exc:
            await self._record_retry(
                recipient_id,
                broadcast_id,
                previous_attempts,
                exc,
                delay_seconds=max(1, exc.retry_after),
            )
        except (TelegramNetworkError, TelegramServerError) as exc:
            delay = min(60, 2 ** (previous_attempts + 1))
            await self._record_retry(
                recipient_id,
                broadcast_id,
                previous_attempts,
                exc,
                delay_seconds=delay,
            )
        except (TelegramForbiddenError, TelegramNotFound, TelegramBadRequest) as exc:
            await self._record_failure(
                recipient_id,
                broadcast_id,
                telegram_id,
                exc,
                unreachable=_is_permanently_unreachable(exc),
            )
        except TelegramAPIError as exc:
            await self._record_failure(
                recipient_id,
                broadcast_id,
                telegram_id,
                exc,
                unreachable=False,
            )
        except Exception as exc:
            delay = min(60, 2 ** (previous_attempts + 1))
            logger.exception(
                "Unexpected broadcast recipient failure",
                extra={"broadcast_id": broadcast_id, "telegram_id": telegram_id},
            )
            await self._record_retry(
                recipient_id,
                broadcast_id,
                previous_attempts,
                exc,
                delay_seconds=delay,
            )
        else:
            async with self.session_factory.begin() as session:
                await session.execute(
                    update(BroadcastRecipient)
                    .where(BroadcastRecipient.id == recipient_id)
                    .values(
                        status=BroadcastRecipientStatus.SENT,
                        attempt_count=previous_attempts + 1,
                        next_attempt_at=None,
                        last_error=None,
                        sent_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
                current = await get_broadcast(session, broadcast_id)
                if current is not None:
                    await _finalize_broadcast(session, current)

        if not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=SEND_INTERVAL_SECONDS)
            except TimeoutError:
                pass
        return True

    async def _record_retry(
        self,
        recipient_id: int,
        broadcast_id: int,
        previous_attempts: int,
        error: Exception,
        *,
        delay_seconds: int,
    ) -> None:
        attempts = previous_attempts + 1
        terminal = attempts >= MAX_ATTEMPTS
        async with self.session_factory.begin() as session:
            await session.execute(
                update(BroadcastRecipient)
                .where(BroadcastRecipient.id == recipient_id)
                .values(
                    status=(
                        BroadcastRecipientStatus.FAILED
                        if terminal
                        else BroadcastRecipientStatus.PENDING
                    ),
                    attempt_count=attempts,
                    next_attempt_at=(
                        None if terminal else datetime.now(UTC) + timedelta(seconds=delay_seconds)
                    ),
                    last_error=str(error)[:MAX_ERROR_LENGTH],
                    updated_at=datetime.now(UTC),
                )
            )
            current = await get_broadcast(session, broadcast_id)
            if current is not None:
                await _finalize_broadcast(session, current)

    async def _record_failure(
        self,
        recipient_id: int,
        broadcast_id: int,
        telegram_id: int,
        error: Exception,
        *,
        unreachable: bool,
    ) -> None:
        async with self.session_factory.begin() as session:
            await session.execute(
                update(BroadcastRecipient)
                .where(BroadcastRecipient.id == recipient_id)
                .values(
                    status=BroadcastRecipientStatus.FAILED,
                    attempt_count=BroadcastRecipient.attempt_count + 1,
                    next_attempt_at=None,
                    last_error=str(error)[:MAX_ERROR_LENGTH],
                    updated_at=datetime.now(UTC),
                )
            )
            if unreachable:
                await mark_user_unreachable(session, telegram_id)
            current = await get_broadcast(session, broadcast_id)
            if current is not None:
                await _finalize_broadcast(session, current)
