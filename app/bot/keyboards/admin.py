from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import (
    AdminCallback,
    AdminLessonCallback,
    AdminOptionCallback,
    BroadcastCallback,
    ChannelCallback,
    LessonVideoCallback,
    OptionItemCallback,
    StatisticsCallback,
)
from app.db.models import (
    BroadcastStatus,
    Channel,
    ContentOption,
    MediaType,
    OptionContentItem,
    VideoLesson,
    VideoLessonVideo,
)
from app.i18n import Language, tr
from app.services.channels import ChannelPage
from app.services.content import localized_content_text
from app.services.lessons import (
    LessonPage,
    LessonVideoPage,
    localized_lesson_title,
)
from app.services.options import (
    OptionItemPage,
    OptionPage,
    localized_option_name,
)
from app.services.statistics import UserPage


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
            [
                InlineKeyboardButton(
                    text=tr(language, "admin_manage_lessons"),
                    callback_data=AdminCallback(action="lessons").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "admin_statistics"),
                    callback_data=AdminCallback(action="statistics").pack(),
                )
            ],
        ]
    )


def lesson_draft_keyboard(language: Language, *, can_save: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_save:
        rows.append(
            [
                InlineKeyboardButton(
                    text=tr(language, "lesson_save"),
                    callback_data=AdminLessonCallback(
                        action="create_save", lesson_id=0, page=0
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=tr(language, "back_to_menu"),
                callback_data=AdminCallback(action="menu").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lesson_list_keyboard(result: LessonPage, language: Language) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=("🟢 " if lesson.is_active else "🔴 ")
                + localized_lesson_title(lesson, language),
                callback_data=AdminLessonCallback(
                    action="view", lesson_id=lesson.id, page=result.page
                ).pack(),
            )
        ]
        for lesson in result.items
    ]
    navigation: list[InlineKeyboardButton] = []
    if result.page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=AdminLessonCallback(
                    action="page", lesson_id=0, page=result.page - 1
                ).pack(),
            )
        )
    if result.page < result.pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=AdminLessonCallback(
                    action="page", lesson_id=0, page=result.page + 1
                ).pack(),
            )
        )
    if navigation:
        rows.append(navigation)
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=tr(language, "lesson_add"),
                    callback_data=AdminLessonCallback(
                        action="add", lesson_id=0, page=result.page
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


def lesson_detail_keyboard(
    lesson: VideoLesson, page: int, language: Language
) -> InlineKeyboardMarkup:
    toggle = "disable" if lesson.is_active else "enable"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "lesson_videos"),
                    callback_data=AdminLessonCallback(
                        action="videos", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=tr(language, "lesson_preview"),
                    callback_data=AdminLessonCallback(
                        action="preview", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🇺🇿 ✏️ {tr(language, 'lesson_title_label')}",
                    callback_data=AdminLessonCallback(
                        action="title_uz", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=f"🇷🇺 ✏️ {tr(language, 'lesson_title_label')}",
                    callback_data=AdminLessonCallback(
                        action="title_ru", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=f"🇬🇧 ✏️ {tr(language, 'lesson_title_label')}",
                    callback_data=AdminLessonCallback(
                        action="title_en", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🇺🇿 ✏️ {tr(language, 'lesson_text_label')}",
                    callback_data=AdminLessonCallback(
                        action="text_uz", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=f"🇷🇺 ✏️ {tr(language, 'lesson_text_label')}",
                    callback_data=AdminLessonCallback(
                        action="text_ru", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=f"🇬🇧 ✏️ {tr(language, 'lesson_text_label')}",
                    callback_data=AdminLessonCallback(
                        action="text_en", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, toggle),
                    callback_data=AdminLessonCallback(
                        action=toggle, lesson_id=lesson.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬆️",
                    callback_data=AdminLessonCallback(
                        action="up", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="⬇️",
                    callback_data=AdminLessonCallback(
                        action="down", lesson_id=lesson.id, page=page
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "delete"),
                    callback_data=AdminLessonCallback(
                        action="delete_request", lesson_id=lesson.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "back"),
                    callback_data=AdminLessonCallback(action="page", lesson_id=0, page=page).pack(),
                )
            ],
        ]
    )


def lesson_delete_keyboard(
    lesson: VideoLesson, page: int, language: Language
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "confirm_delete"),
                    callback_data=AdminLessonCallback(
                        action="delete_confirm", lesson_id=lesson.id, page=page
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "cancel"),
                    callback_data=AdminLessonCallback(
                        action="view", lesson_id=lesson.id, page=page
                    ).pack(),
                )
            ],
        ]
    )


def lesson_videos_keyboard(
    lesson: VideoLesson,
    result: LessonVideoPage,
    lesson_page: int,
    language: Language,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🎬 {index + 1 + result.page * 8}",
                callback_data=LessonVideoCallback(
                    action="view",
                    video_id=video.id,
                    lesson_id=lesson.id,
                    page=result.page,
                    lesson_page=lesson_page,
                ).pack(),
            )
        ]
        for index, video in enumerate(result.items)
    ]
    navigation: list[InlineKeyboardButton] = []
    if result.page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=LessonVideoCallback(
                    action="page",
                    video_id=0,
                    lesson_id=lesson.id,
                    page=result.page - 1,
                    lesson_page=lesson_page,
                ).pack(),
            )
        )
    if result.page < result.pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=LessonVideoCallback(
                    action="page",
                    video_id=0,
                    lesson_id=lesson.id,
                    page=result.page + 1,
                    lesson_page=lesson_page,
                ).pack(),
            )
        )
    if navigation:
        rows.append(navigation)
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=tr(language, "lesson_video_add"),
                    callback_data=LessonVideoCallback(
                        action="add",
                        video_id=0,
                        lesson_id=lesson.id,
                        page=result.page,
                        lesson_page=lesson_page,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "back"),
                    callback_data=AdminLessonCallback(
                        action="view", lesson_id=lesson.id, page=lesson_page
                    ).pack(),
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lesson_video_detail_keyboard(
    video: VideoLessonVideo, page: int, lesson_page: int, language: Language
) -> InlineKeyboardMarkup:
    data = dict(
        video_id=video.id,
        lesson_id=video.lesson_id,
        page=page,
        lesson_page=lesson_page,
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "lesson_video_replace"),
                    callback_data=LessonVideoCallback(action="replace", **data).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬆️", callback_data=LessonVideoCallback(action="up", **data).pack()
                ),
                InlineKeyboardButton(
                    text="⬇️", callback_data=LessonVideoCallback(action="down", **data).pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "delete"),
                    callback_data=LessonVideoCallback(action="delete_request", **data).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "back"),
                    callback_data=LessonVideoCallback(
                        action="page",
                        video_id=0,
                        lesson_id=video.lesson_id,
                        page=page,
                        lesson_page=lesson_page,
                    ).pack(),
                )
            ],
        ]
    )


def lesson_video_delete_keyboard(
    video: VideoLessonVideo, page: int, lesson_page: int, language: Language
) -> InlineKeyboardMarkup:
    data = dict(
        video_id=video.id,
        lesson_id=video.lesson_id,
        page=page,
        lesson_page=lesson_page,
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "confirm_delete"),
                    callback_data=LessonVideoCallback(action="delete_confirm", **data).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "cancel"),
                    callback_data=LessonVideoCallback(action="view", **data).pack(),
                )
            ],
        ]
    )


def statistics_keyboard(language: Language) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "statistics_users"),
                    callback_data=StatisticsCallback(action="users", user_id=0, page=0).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "statistics_export_csv"),
                    callback_data=StatisticsCallback(action="export_csv", user_id=0, page=0).pack(),
                ),
                InlineKeyboardButton(
                    text=tr(language, "statistics_export_xlsx"),
                    callback_data=StatisticsCallback(
                        action="export_xlsx", user_id=0, page=0
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=tr(language, "statistics_refresh"),
                    callback_data=StatisticsCallback(action="overview", user_id=0, page=0).pack(),
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


def statistics_users_keyboard(result: UserPage, language: Language) -> InlineKeyboardMarkup:
    rows = []
    for record in result.items:
        user = record.user
        name = " ".join(part for part in (user.first_name, user.last_name) if part)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"👤 {(name or user.username or str(user.telegram_id))[:50]}",
                    callback_data=StatisticsCallback(
                        action="view", user_id=user.id, page=result.page
                    ).pack(),
                )
            ]
        )
    navigation: list[InlineKeyboardButton] = []
    if result.page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=StatisticsCallback(
                    action="users", user_id=0, page=result.page - 1
                ).pack(),
            )
        )
    if result.page < result.pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=StatisticsCallback(
                    action="users", user_id=0, page=result.page + 1
                ).pack(),
            )
        )
    if navigation:
        rows.append(navigation)
    rows.append(
        [
            InlineKeyboardButton(
                text=tr(language, "back"),
                callback_data=StatisticsCallback(action="overview", user_id=0, page=0).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def statistics_user_detail_keyboard(page: int, language: Language) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(language, "back"),
                    callback_data=StatisticsCallback(action="users", user_id=0, page=page).pack(),
                )
            ]
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
