from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot.callbacks import LanguageCallback, SubscriptionCallback
from app.db.models import Channel
from app.i18n import LANGUAGE_BUTTON_TEXT, Language, tr


def language_selector_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇺🇿 O‘zbekcha",
                    callback_data=LanguageCallback(code=Language.UZ.value).pack(),
                ),
                InlineKeyboardButton(
                    text="🇷🇺 Русский",
                    callback_data=LanguageCallback(code=Language.RU.value).pack(),
                ),
                InlineKeyboardButton(
                    text="🇬🇧 English",
                    callback_data=LanguageCallback(code=Language.EN.value).pack(),
                ),
            ]
        ]
    )


def language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=LANGUAGE_BUTTON_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def contact_keyboard(language: Language) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=tr(language, "share_phone"), request_contact=True)],
            [KeyboardButton(text=LANGUAGE_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=tr(language, "share_phone_placeholder"),
    )


def subscription_keyboard(
    channels: tuple[Channel, ...], language: Language
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=tr(language, "join_channel", title=channel.title)[:64],
                url=channel.join_url,
            )
        ]
        for channel in channels
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=tr(language, "check_subscription"),
                callback_data=SubscriptionCallback(action="check").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
