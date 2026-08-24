from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMember, ChatMemberRestricted


class SubscriptionCheckError(RuntimeError):
    """Telegram could not determine the user's channel membership."""


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
