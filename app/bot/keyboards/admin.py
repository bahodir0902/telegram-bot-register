from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import AdminCallback, ChannelCallback, MediaCallback
from app.db.models import Channel, Media, MediaType
from app.i18n import Language, tr
from app.services.channels import ChannelPage
from app.services.media import MediaPage


def admin_menu_keyboard(language: Language) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "admin_add_media"),
                    callback_data=AdminCallback(action="add").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "admin_manage_media"),
                    callback_data=AdminCallback(action="manage").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "admin_manage_channels"),
                    callback_data=AdminCallback(action="channels").pack(),
                )
            ],
        ]
    )


def upload_cancel_keyboard(language: Language) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "back_to_menu"),
                    callback_data=AdminCallback(action="menu").pack(),
                )
            ]
        ]
    )


def media_label(item: Media) -> str:
    icons = {
        MediaType.VIDEO: "🎬",
        MediaType.PHOTO: "🖼",
        MediaType.DOCUMENT: "📄",
    }
    name = item.original_filename or f"{item.media_type.value}-{item.id}"
    name = name if len(name) <= 40 else f"{name[:37]}..."
    status = "🟢" if item.is_active else "🔴"
    return f"{icons[item.media_type]} {name} {status}"


def media_list_keyboard(result: MediaPage, language: Language) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=media_label(item),
                callback_data=MediaCallback(
                    action="view", media_id=item.id, page=result.page
                ).pack(),
            )
        ]
        for item in result.items
    ]

    navigation: list[InlineKeyboardButton] = []
    if result.page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=MediaCallback(action="page", media_id=0, page=result.page - 1).pack(),
            )
        )
    if result.page < result.pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=MediaCallback(action="page", media_id=0, page=result.page + 1).pack(),
            )
        )
    if navigation:
        rows.append(navigation)
    rows.append(
        [
            InlineKeyboardButton(
                text=tr(language, "admin_menu_button"),
                callback_data=AdminCallback(action="menu").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def media_detail_keyboard(item: Media, page: int, language: Language) -> InlineKeyboardMarkup:
    action = "disable" if item.is_active else "enable"
    label = tr(language, "disable" if item.is_active else "enable")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=MediaCallback(action=action, media_id=item.id, page=page).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "delete"),
                    callback_data=MediaCallback(
                        action="delete_request", media_id=item.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "back"),
                    callback_data=MediaCallback(action="page", media_id=0, page=page).pack(),
                )
            ],
        ]
    )


def media_delete_keyboard(item: Media, page: int, language: Language) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "confirm_delete"),
                    callback_data=MediaCallback(
                        action="delete_confirm", media_id=item.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "cancel"),
                    callback_data=MediaCallback(action="view", media_id=item.id, page=page).pack(),
                )
            ],
        ]
    )


def channel_list_keyboard(result: ChannelPage, language: Language) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"📢 {channel.title}"[:64],
                callback_data=ChannelCallback(
                    action="view", channel_id=channel.id, page=result.page
                ).pack(),
            )
        ]
        for channel in result.items
    ]
    navigation: list[InlineKeyboardButton] = []
    if result.page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=ChannelCallback(
                    action="page", channel_id=0, page=result.page - 1
                ).pack(),
            )
        )
    if result.page < result.pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=ChannelCallback(
                    action="page", channel_id=0, page=result.page + 1
                ).pack(),
            )
        )
    if navigation:
        rows.append(navigation)
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=tr(language, "channel_add"),
                    callback_data=ChannelCallback(
                        action="add", channel_id=0, page=result.page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "admin_menu_button"),
                    callback_data=AdminCallback(action="menu").pack(),
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def channel_detail_keyboard(
    channel: Channel, page: int, language: Language
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "channel_edit_id"),
                    callback_data=ChannelCallback(
                        action="edit_id", channel_id=channel.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "channel_edit_url"),
                    callback_data=ChannelCallback(
                        action="edit_url", channel_id=channel.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "delete"),
                    callback_data=ChannelCallback(
                        action="delete_request", channel_id=channel.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "back"),
                    callback_data=ChannelCallback(action="page", channel_id=0, page=page).pack(),
                )
            ],
        ]
    )


def channel_delete_keyboard(
    channel: Channel, page: int, language: Language
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "confirm_delete"),
                    callback_data=ChannelCallback(
                        action="delete_confirm", channel_id=channel.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "cancel"),
                    callback_data=ChannelCallback(
                        action="view", channel_id=channel.id, page=page
                    ).pack(),
                )
            ],
        ]
    )
