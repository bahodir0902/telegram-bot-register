from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import (
    AdminCallback,
    AdminOptionCallback,
    BroadcastCallback,
    ChannelCallback,
    OptionItemCallback,
)
from app.db.models import (
    BroadcastStatus,
    Channel,
    ContentOption,
    MediaType,
    OptionContentItem,
)
from app.i18n import Language, tr
from app.services.channels import ChannelPage
from app.services.content import localized_content_text
from app.services.options import (
    OptionItemPage,
    OptionPage,
    localized_option_name,
)


def admin_menu_keyboard(language: Language) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "admin_add_content"),
                    callback_data=AdminCallback(action="add").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "admin_manage_content"),
                    callback_data=AdminCallback(action="manage").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "admin_send_broadcast"),
                    callback_data=AdminCallback(action="broadcast").pack(),
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


def option_label(option: ContentOption, language: Language) -> str:
    status = "🟢" if option.is_active else "🔴"
    return f"{status} {localized_option_name(option, language)}"


def option_list_keyboard(result: OptionPage, language: Language) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=option_label(option, language),
                callback_data=AdminOptionCallback(
                    action="view", option_id=option.id, page=result.page
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
                callback_data=AdminOptionCallback(
                    action="page", option_id=0, page=result.page - 1
                ).pack(),
            )
        )
    if result.page < result.pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=AdminOptionCallback(
                    action="page", option_id=0, page=result.page + 1
                ).pack(),
            )
        )
    if navigation:
        rows.append(navigation)
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=tr(language, "option_add"),
                    callback_data=AdminCallback(action="add").pack(),
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


def option_detail_keyboard(
    option: ContentOption, page: int, language: Language
) -> InlineKeyboardMarkup:
    active_action = "disable" if option.is_active else "enable"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, active_action),
                    callback_data=AdminOptionCallback(
                        action=active_action, option_id=option.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=tr(language, "option_items"),
                    callback_data=AdminOptionCallback(
                        action="items", option_id=option.id, page=page
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🇺🇿 ✏️",
                    callback_data=AdminOptionCallback(
                        action="name_uz", option_id=option.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🇷🇺 ✏️",
                    callback_data=AdminOptionCallback(
                        action="name_ru", option_id=option.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🇬🇧 ✏️",
                    callback_data=AdminOptionCallback(
                        action="name_en", option_id=option.id, page=page
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬆️",
                    callback_data=AdminOptionCallback(
                        action="up", option_id=option.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="⬇️",
                    callback_data=AdminOptionCallback(
                        action="down", option_id=option.id, page=page
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "delete"),
                    callback_data=AdminOptionCallback(
                        action="delete_request", option_id=option.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "back"),
                    callback_data=AdminOptionCallback(action="page", option_id=0, page=page).pack(),
                )
            ],
        ]
    )


def option_delete_keyboard(
    option: ContentOption, page: int, language: Language
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "confirm_delete"),
                    callback_data=AdminOptionCallback(
                        action="delete_confirm", option_id=option.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "cancel"),
                    callback_data=AdminOptionCallback(
                        action="view", option_id=option.id, page=page
                    ).pack(),
                )
            ],
        ]
    )


def option_item_label(item: OptionContentItem, language: Language) -> str:
    icons = {
        MediaType.TEXT: "💬",
        MediaType.VIDEO: "🎬",
        MediaType.PHOTO: "🖼",
        MediaType.DOCUMENT: "📄",
    }
    name = (
        item.original_filename
        or localized_content_text(item, language)
        or f"{item.media_type.value}-{item.id}"
    )
    name = name.replace("\n", " ")
    name = name if len(name) <= 40 else f"{name[:37]}..."
    return f"{icons[item.media_type]} {name}"


def option_items_keyboard(
    option: ContentOption,
    result: OptionItemPage,
    option_page: int,
    language: Language,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=option_item_label(item, language),
                callback_data=OptionItemCallback(
                    action="view",
                    item_id=item.id,
                    option_id=option.id,
                    page=result.page,
                    option_page=option_page,
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
                callback_data=OptionItemCallback(
                    action="page",
                    item_id=0,
                    option_id=option.id,
                    page=result.page - 1,
                    option_page=option_page,
                ).pack(),
            )
        )
    if result.page < result.pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=OptionItemCallback(
                    action="page",
                    item_id=0,
                    option_id=option.id,
                    page=result.page + 1,
                    option_page=option_page,
                ).pack(),
            )
        )
    if navigation:
        rows.append(navigation)
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=tr(language, "option_item_add"),
                    callback_data=OptionItemCallback(
                        action="add",
                        item_id=0,
                        option_id=option.id,
                        page=result.page,
                        option_page=option_page,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "back"),
                    callback_data=AdminOptionCallback(
                        action="view", option_id=option.id, page=option_page
                    ).pack(),
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def option_item_detail_keyboard(
    item: OptionContentItem, page: int, option_page: int, language: Language
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇺🇿 ✏️",
                    callback_data=OptionItemCallback(
                        action="text_uz",
                        item_id=item.id,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🇷🇺 ✏️",
                    callback_data=OptionItemCallback(
                        action="text_ru",
                        item_id=item.id,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🇬🇧 ✏️",
                    callback_data=OptionItemCallback(
                        action="text_en",
                        item_id=item.id,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "option_item_replace"),
                    callback_data=OptionItemCallback(
                        action="replace",
                        item_id=item.id,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬆️",
                    callback_data=OptionItemCallback(
                        action="up",
                        item_id=item.id,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="⬇️",
                    callback_data=OptionItemCallback(
                        action="down",
                        item_id=item.id,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "delete"),
                    callback_data=OptionItemCallback(
                        action="delete_request",
                        item_id=item.id,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "back"),
                    callback_data=OptionItemCallback(
                        action="page",
                        item_id=0,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                )
            ],
        ]
    )


def option_item_delete_keyboard(
    item: OptionContentItem, page: int, option_page: int, language: Language
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "confirm_delete"),
                    callback_data=OptionItemCallback(
                        action="delete_confirm",
                        item_id=item.id,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "cancel"),
                    callback_data=OptionItemCallback(
                        action="view",
                        item_id=item.id,
                        option_id=item.option_id,
                        page=page,
                        option_page=option_page,
                    ).pack(),
                )
            ],
        ]
    )


def option_creation_more_keyboard(language: Language) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "option_add_more"),
                    callback_data=AdminOptionCallback(
                        action="create_more", option_id=0, page=0
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=tr(language, "option_finish"),
                    callback_data=AdminOptionCallback(
                        action="create_finish", option_id=0, page=0
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "cancel"),
                    callback_data=AdminCallback(action="menu").pack(),
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


def broadcast_preview_keyboard(language: Language) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "broadcast_confirm"),
                    callback_data=BroadcastCallback(action="confirm", broadcast_id=0).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "cancel"),
                    callback_data=BroadcastCallback(action="cancel_draft", broadcast_id=0).pack(),
                )
            ],
        ]
    )


def broadcast_status_keyboard(
    broadcast_id: int,
    status: BroadcastStatus,
    language: Language,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=tr(language, "broadcast_refresh"),
                callback_data=BroadcastCallback(action="status", broadcast_id=broadcast_id).pack(),
            )
        ]
    ]
    if status in {BroadcastStatus.QUEUED, BroadcastStatus.RUNNING}:
        rows.append(
            [
                InlineKeyboardButton(
                    text=tr(language, "broadcast_cancel_pending"),
                    callback_data=BroadcastCallback(
                        action="cancel", broadcast_id=broadcast_id
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=tr(language, "admin_menu_button"),
                callback_data=AdminCallback(action="menu").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
