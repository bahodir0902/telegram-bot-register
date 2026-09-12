from __future__ import annotations

from datetime import UTC, datetime
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.callbacks import AdminCallback, StatisticsCallback
from app.bot.filters.admin import AdminFilter, is_admin_user
from app.bot.keyboards.admin import (
    statistics_keyboard,
    statistics_user_detail_keyboard,
    statistics_users_keyboard,
)
from app.bot.messages import answer_callback_safely, edit_text_safely
from app.config import Settings
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr
from app.services.lessons import get_lesson, localized_lesson_title
from app.services.options import get_option, localized_option_name
from app.services.statistics import (
    UserRecord,
    all_user_records,
    build_users_csv,
    build_users_xlsx,
    get_statistics_overview,
    get_user_record,
    list_user_records,
)
from app.services.users import display_start_source

router = Router(name="admin_statistics")


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%d %H:%M UTC")


async def statistics_text(language: Language, session_factory: AsyncSessionFactory) -> str:
    async with session_factory() as session:
        overview = await get_statistics_overview(session)
        recipe_names: list[str] = []
        for target_id, views in overview.top_recipes:
            option = await get_option(session, target_id)
            name = (
                localized_option_name(option, language)
                if option is not None
                else tr(language, "statistics_deleted_content", id=target_id)
            )
            recipe_names.append(f"• {escape(name)} — {views}")
        lesson_names: list[str] = []
        for target_id, views in overview.top_lessons:
            lesson = await get_lesson(session, target_id)
            name = (
                localized_lesson_title(lesson, language)
                if lesson is not None
                else tr(language, "statistics_deleted_content", id=target_id)
            )
            lesson_names.append(f"• {escape(name)} — {views}")
    languages = (
        " · ".join(f"{code.upper()}: {count}" for code, count in sorted(overview.languages.items()))
        or "—"
    )
    sources = (
        "\n".join(f"• {escape(source)} — {count}" for source, count in overview.sources) or "—"
    )
    return tr(
        language,
        "statistics_overview",
        total=overview.total_users,
        phone=overview.phone_verified,
        subscribed=overview.subscription_verified,
        reachable=overview.reachable,
        unreachable=overview.unreachable,
        day=overview.new_24h,
        week=overview.new_7d,
        month=overview.new_30d,
        languages=languages,
        sources=sources,
        recipe_views=overview.recipe_views,
        recipe_viewers=overview.recipe_viewers,
        lesson_views=overview.lesson_views,
        lesson_viewers=overview.lesson_viewers,
        top_recipes="\n".join(recipe_names) or "—",
        top_lessons="\n".join(lesson_names) or "—",
    )


def user_detail_text(record: UserRecord, language: Language) -> str:
    user = record.user
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part) or "—"
    username = f"@{user.username}" if user.username else "—"
    return tr(
        language,
        "statistics_user_detail",
        telegram_id=user.telegram_id,
        username=escape(username),
        name=escape(full_name),
        phone=escape(user.phone_number or "—"),
        language_code=user.language_code.value.upper() if user.language_code else "—",
        first_started=_format_datetime(user.first_started_at or user.created_at),
        last_started=_format_datetime(user.last_started_at),
        first_source=escape(display_start_source(user.first_start_source)),
        last_source=escape(display_start_source(user.last_start_source)),
        phone_verified=_format_datetime(user.phone_verified_at),
        subscription_verified=_format_datetime(user.subscription_verified_at),
        reachable=tr(language, "yes" if user.is_reachable else "no"),
        recipes=record.engagement.recipes,
        lessons=record.engagement.lessons,
    )


@router.callback_query(AdminCallback.filter(F.action == "statistics"), AdminFilter())
async def open_statistics(
    callback: CallbackQuery,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            await statistics_text(language, session_factory),
            reply_markup=statistics_keyboard(language),
        )


@router.callback_query(StatisticsCallback.filter(F.action == "overview"), AdminFilter())
async def refresh_statistics(
    callback: CallbackQuery,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await open_statistics(callback, language, session_factory)


@router.callback_query(StatisticsCallback.filter(F.action == "users"), AdminFilter())
async def show_statistics_users(
    callback: CallbackQuery,
    callback_data: StatisticsCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    await answer_callback_safely(callback)
    async with session_factory() as session:
        result = await list_user_records(session, page=callback_data.page)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            tr(
                language,
                "statistics_users_title",
                total=result.total,
                page=result.page + 1,
                pages=result.pages,
            ),
            reply_markup=statistics_users_keyboard(result, language),
        )


@router.callback_query(StatisticsCallback.filter(F.action == "view"), AdminFilter())
async def show_statistics_user_detail(
    callback: CallbackQuery,
    callback_data: StatisticsCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    async with session_factory() as session:
        record = await get_user_record(session, callback_data.user_id)
    if record is None:
        await answer_callback_safely(
            callback, tr(language, "statistics_user_missing"), show_alert=True
        )
        return
    await answer_callback_safely(callback)
    if isinstance(callback.message, Message):
        await edit_text_safely(
            callback.message,
            user_detail_text(record, language),
            reply_markup=statistics_user_detail_keyboard(callback_data.page, language),
        )


@router.callback_query(
    StatisticsCallback.filter(F.action.in_({"export_csv", "export_xlsx"})), AdminFilter()
)
async def export_statistics_users(
    callback: CallbackQuery,
    callback_data: StatisticsCallback,
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    message = callback.message
    if not isinstance(message, Message) or message.chat.type != ChatType.PRIVATE:
        await answer_callback_safely(callback, tr(language, "admin_private_only"), show_alert=True)
        return
    await answer_callback_safely(callback, tr(language, "statistics_export_preparing"))
    async with session_factory() as session:
        records = await all_user_records(session)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    if callback_data.action == "export_csv":
        payload = build_users_csv(records)
        filename = f"users_{timestamp}.csv"
    else:
        payload = build_users_xlsx(records)
        filename = f"users_{timestamp}.xlsx"
    await message.answer_document(
        BufferedInputFile(payload, filename=filename),
        caption=tr(language, "statistics_export_ready", count=len(records)),
    )


@router.callback_query(StatisticsCallback.filter())
async def reject_statistics_callback(
    callback: CallbackQuery, settings: Settings, language: Language
) -> None:
    sender_id = callback.from_user.id if callback.from_user else None
    await answer_callback_safely(
        callback,
        tr(
            language,
            "admin_callback_stale"
            if is_admin_user(sender_id, settings.admin_ids)
            else "admin_action_unauthorized",
        ),
        show_alert=True,
    )
