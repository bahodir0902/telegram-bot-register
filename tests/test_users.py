import pytest
from sqlalchemy import func, select

from app.db.models import User
from app.db.session import Database
from app.services.users import (
    claim_subscription_prompt,
    contact_belongs_to_user,
    get_user,
    normalize_phone_number,
    set_subscription_prompt,
    upsert_user,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+998 90 123-45-67", "+998901234567"),
        ("00998 (90) 123 45 67", "+998901234567"),
        ("998901234567", "+998901234567"),
    ],
)
def test_phone_normalization(raw: str, expected: str) -> None:
    assert normalize_phone_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "123", "+" + "1" * 16])
def test_phone_normalization_rejects_invalid_length(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone_number(raw)


def test_contact_must_belong_to_sender() -> None:
    assert contact_belongs_to_user(10, 10)
    assert not contact_belongs_to_user(11, 10)
    assert not contact_belongs_to_user(None, 10)


async def test_user_upsert_is_idempotent(database: Database) -> None:
    async with database.session_factory.begin() as session:
        first = await upsert_user(
            session,
            telegram_id=42,
            username="before",
            first_name="First",
            last_name=None,
        )
        first_id = first.id
    async with database.session_factory.begin() as session:
        second = await upsert_user(
            session,
            telegram_id=42,
            username="after",
            first_name="Updated",
            last_name="Name",
        )
        count = await session.scalar(select(func.count(User.id)))

    assert second.id == first_id
    assert second.username == "after"
    assert count == 1


async def test_subscription_prompt_can_only_be_claimed_once(database: Database) -> None:
    async with database.session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=42,
            username=None,
            first_name="User",
            last_name=None,
        )
        await set_subscription_prompt(session, 42, 99)

    async with database.session_factory.begin() as session:
        assert await claim_subscription_prompt(session, 42, 99)
    async with database.session_factory.begin() as session:
        assert not await claim_subscription_prompt(session, 42, 99)
        user = await get_user(session, 42)

    assert user is not None
    assert user.subscription_prompt_message_id is None
    assert user.subscription_verified_at is not None
