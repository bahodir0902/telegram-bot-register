from datetime import UTC, datetime

import pytest
from aiogram.types import ChatMemberLeft, ChatMemberMember, ChatMemberRestricted, User

from app.services import subscription as subscription_service
from app.services.subscription import (
    SubscriptionCheckError,
    check_subscriptions,
    membership_is_subscribed,
)
from tests.test_channels import make_channel


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


async def test_all_channels_are_checked_and_results_are_aggregated(monkeypatch) -> None:
    channels = (
        make_channel(1, "@first_channel", "First"),
        make_channel(2, "@second_channel", "Second"),
        make_channel(3, "@third_channel", "Third"),
    )

    async def subscribed(_bot, channel_id, _user_id):
        if channel_id == "@third_channel":
            raise SubscriptionCheckError
        return channel_id == "@first_channel"

    monkeypatch.setattr(subscription_service, "is_subscribed", subscribed)
    result = await check_subscriptions(object(), channels, 42)

    assert result.missing == (channels[1],)
    assert result.failed == (channels[2],)
