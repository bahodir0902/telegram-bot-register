from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import AdminCallback, MediaCallback
from app.db.models import Media, MediaType
from app.services.media import MediaPage


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Add media",
                    callback_data=AdminCallback(action="add").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Manage media",
                    callback_data=AdminCallback(action="manage").pack(),
                )
            ],
        ]
    )


def upload_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◀️ Back to menu",
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


def media_list_keyboard(result: MediaPage) -> InlineKeyboardMarkup:
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
                text="◀️ Admin menu",
                callback_data=AdminCallback(action="menu").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def media_detail_keyboard(item: Media, page: int) -> InlineKeyboardMarkup:
    action = "disable" if item.is_active else "enable"
    label = "🔴 Disable" if item.is_active else "🟢 Enable"
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
                    text="🗑 Delete",
                    callback_data=MediaCallback(
                        action="delete_request", media_id=item.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Back",
                    callback_data=MediaCallback(action="page", media_id=0, page=page).pack(),
                )
            ],
        ]
    )


def media_delete_keyboard(item: Media, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠️ Yes, delete",
                    callback_data=MediaCallback(
                        action="delete_confirm", media_id=item.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Cancel",
                    callback_data=MediaCallback(action="view", media_id=item.id, page=page).pack(),
                )
            ],
        ]
    )
