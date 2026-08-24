from datetime import UTC, datetime

import pytest
from aiogram.types import ChatMemberLeft, ChatMemberMember, ChatMemberRestricted, User

from app.services.subscription import membership_is_subscribed


def telegram_user() -> User:
    return User(id=42, is_bot=False, first_name="Test")


def restricted_member(is_member: bool) -> ChatMemberRestricted:
    permissions = {
        name: False
        for name, field in ChatMemberRestricted.model_fields.items()
        if name.startswith("can_") and field.is_required()
    }
    return ChatMemberRestricted(
        user=telegram_user(),
        is_member=is_member,
        until_date=datetime.now(UTC),
        **permissions,
    )


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        (ChatMemberMember(user=telegram_user()), True),
        (ChatMemberLeft(user=telegram_user()), False),
        (restricted_member(True), True),
        (restricted_member(False), False),
    ],
)
def test_membership_status_interpretation(member, expected: bool) -> None:
    assert membership_is_subscribed(member) is expected
