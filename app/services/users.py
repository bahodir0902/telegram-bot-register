from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.i18n import DEFAULT_LANGUAGE, Language

PHONE_DIGIT_RE = re.compile(r"\D")


def contact_belongs_to_user(contact_user_id: int | None, sender_id: int) -> bool:
    return contact_user_id is not None and contact_user_id == sender_id


def normalize_phone_number(phone_number: str) -> str:
    digits = PHONE_DIGIT_RE.sub("", phone_number)
    if digits.startswith("00"):
        digits = digits[2:]
    if not 7 <= len(digits) <= 15:
        raise ValueError("Phone number must contain between 7 and 15 digits")
    return f"+{digits}"


async def upsert_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> User:
    now = datetime.now(UTC)
    statement = (
        sqlite_insert(User)
        .values(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_reachable=True,
            unreachable_at=None,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[User.telegram_id],
            set_={
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "is_reachable": True,
                "unreachable_at": None,
                "updated_at": now,
            },
        )
        .returning(User)
    )
    return (await session.execute(statement)).scalar_one()


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def get_user_language(session: AsyncSession, telegram_id: int) -> Language:
    value = await session.scalar(select(User.language_code).where(User.telegram_id == telegram_id))
    return value or DEFAULT_LANGUAGE


async def set_user_language(session: AsyncSession, telegram_id: int, language: Language) -> None:
    await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(language_code=language, updated_at=datetime.now(UTC))
    )


async def verify_phone(session: AsyncSession, telegram_id: int, phone_number: str) -> None:
    now = datetime.now(UTC)
    await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(phone_number=phone_number, phone_verified_at=now, updated_at=now)
    )


async def mark_user_unreachable(session: AsyncSession, telegram_id: int) -> None:
    now = datetime.now(UTC)
    await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(is_reachable=False, unreachable_at=now, updated_at=now)
    )


async def mark_user_reachable(session: AsyncSession, telegram_id: int) -> None:
    await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id, User.is_reachable.is_(False))
        .values(is_reachable=True, unreachable_at=None, updated_at=datetime.now(UTC))
    )


async def set_subscription_prompt(session: AsyncSession, telegram_id: int, message_id: int) -> None:
    await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(subscription_prompt_message_id=message_id, updated_at=datetime.now(UTC))
    )


async def mark_subscription_verified(session: AsyncSession, telegram_id: int) -> bool:
    now = datetime.now(UTC)
    result = await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(subscription_verified_at=now, updated_at=now)
    )
    return result.rowcount == 1


async def claim_subscription_prompt(
    session: AsyncSession, telegram_id: int, message_id: int
) -> bool:
    """Claim a prompt once while always recording the latest live membership check."""

    now = datetime.now(UTC)
    result = await session.execute(
        update(User)
        .where(
            User.telegram_id == telegram_id,
            User.subscription_prompt_message_id == message_id,
        )
        .values(
            subscription_prompt_message_id=None,
            subscription_verified_at=now,
            updated_at=now,
        )
    )
    claimed = result.rowcount == 1
    if not claimed:
        await session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(subscription_verified_at=now, updated_at=now)
        )
    return claimed
