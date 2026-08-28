from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot.callbacks import LanguageCallback, SubscriptionCallback, UserOptionCallback
from app.db.models import Channel
from app.i18n import LANGUAGE_BUTTON_TEXT, Language, tr
from app.services.options import OptionPage, localized_option_name


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


def language_keyboard(language: Language) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=LANGUAGE_BUTTON_TEXT)],
            [KeyboardButton(text=tr(language, "show_options"))],
        ],
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


def options_keyboard(result: OptionPage, language: Language) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=localized_option_name(option, language),
                callback_data=UserOptionCallback(
                    action="select", option_id=option.id, page=result.page
                ).pack(),
            )
        ]
        for option in result.items
    ]
    navigation: list[InlineKeyboardButton] = []
    if result.page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=UserOptionCallback(
                    action="page", option_id=0, page=result.page - 1
                ).pack(),
            )
        )
    if result.page < result.pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=UserOptionCallback(
                    action="page", option_id=0, page=result.page + 1
                ).pack(),
            )
        )
    if navigation:
        rows.append(navigation)
    return InlineKeyboardMarkup(inline_keyboard=rows)
