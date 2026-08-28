from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from aiogram.types import Message


@dataclass(slots=True)
class _PendingAlbum:
    messages: dict[int, Message] = field(default_factory=dict)
    future: asyncio.Future[tuple[Message, ...]] | None = None
    timer: asyncio.Task[None] | None = None


class AlbumCollector:
    """Debounce Telegram media-group updates and release one ordered bundle."""

    def __init__(self, debounce_seconds: float = 0.75) -> None:
        self.debounce_seconds = debounce_seconds
        self._pending: dict[tuple[int, int, str], _PendingAlbum] = {}
        self._completed_until: dict[tuple[int, int, str], float] = {}
        self._lock = asyncio.Lock()

    async def collect(self, message: Message) -> tuple[Message, ...] | None:
        group_id = message.media_group_id
        if group_id is None:
            return (message,)
        sender_id = message.from_user.id if message.from_user is not None else 0
        key = (message.chat.id, sender_id, group_id)
        async with self._lock:
            now = asyncio.get_running_loop().time()
            self._completed_until = {
                completed_key: expires_at
                for completed_key, expires_at in self._completed_until.items()
                if expires_at > now
            }
            if key in self._completed_until:
                return None
            pending = self._pending.get(key)
            if pending is None:
                pending = _PendingAlbum()
                pending.future = asyncio.get_running_loop().create_future()
                self._pending[key] = pending
            pending.messages[message.message_id] = message
            if pending.timer is not None:
                pending.timer.cancel()
            pending.timer = asyncio.create_task(self._finish_after_delay(key, pending))
            future = pending.future
        if future is None:  # pragma: no cover - defensive construction boundary
            return None
        album = await asyncio.shield(future)
        return album if message is album[0] else None

    async def _finish_after_delay(self, key: tuple[int, int, str], pending: _PendingAlbum) -> None:
        try:
            await asyncio.sleep(self.debounce_seconds)
            async with self._lock:
                if self._pending.get(key) is not pending:
                    return
                self._pending.pop(key, None)
                self._completed_until[key] = asyncio.get_running_loop().time() + 10.0
                album = tuple(
                    pending.messages[message_id] for message_id in sorted(pending.messages)
                )
                if pending.future is not None and not pending.future.done():
                    pending.future.set_result(album)
        except asyncio.CancelledError:
            return


album_collector = AlbumCollector()
