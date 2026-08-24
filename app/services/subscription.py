from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMember, ChatMemberRestricted

from app.db.models import Channel
from app.services.channels import channel_chat_id


class SubscriptionCheckError(RuntimeError):
    """Telegram could not determine a user's channel membership."""


@dataclass(frozen=True, slots=True)
class SubscriptionResult:
    missing: tuple[Channel, ...]
    failed: tuple[Channel, ...]

    @property
    def successful(self) -> bool:
        return not self.missing and not self.failed


def membership_is_subscribed(member: ChatMember) -> bool:
    if member.status in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    }:
        return True
    return isinstance(member, ChatMemberRestricted) and member.is_member


async def is_subscribed(bot: Bot, channel_id: int | str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    except TelegramAPIError as exc:
        raise SubscriptionCheckError from exc
    return membership_is_subscribed(member)


async def check_subscriptions(
    bot: Bot,
    channels: tuple[Channel, ...],
    user_id: int,
) -> SubscriptionResult:
    results = await asyncio.gather(
        *(is_subscribed(bot, channel_chat_id(channel), user_id) for channel in channels),
        return_exceptions=True,
    )
    missing: list[Channel] = []
    failed: list[Channel] = []
    for channel, result in zip(channels, results, strict=True):
        if isinstance(result, BaseException):
            failed.append(channel)
        elif not result:
            missing.append(channel)
    return SubscriptionResult(tuple(missing), tuple(failed))
