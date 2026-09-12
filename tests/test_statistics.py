import csv
import io
from datetime import datetime

from openpyxl import load_workbook

from app.db.models import EngagementKind
from app.i18n import Language
from app.services.statistics import (
    all_user_records,
    build_users_csv,
    build_users_xlsx,
    get_statistics_overview,
    record_engagement,
)
from app.services.users import (
    get_user,
    record_user_start,
    set_user_language,
    upsert_user,
    verify_phone,
)


async def create_user(database, telegram_id: int, *, name: str = "User") -> None:
    async with database.session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=telegram_id,
            username=f"user{telegram_id}",
            first_name=name,
            last_name="Test",
        )
        await record_user_start(session, telegram_id, "campaign-a")
        await set_user_language(session, telegram_id, Language.EN)
        await verify_phone(session, telegram_id, f"+99890000{telegram_id:04d}")


async def test_start_attribution_preserves_first_and_updates_last(database) -> None:
    await create_user(database, 42)
    async with database.session_factory.begin() as session:
        await record_user_start(session, 42, None)
    async with database.session_factory() as session:
        user = await get_user(session, 42)
    assert user is not None
    assert user.first_start_source == "payload:campaign-a"
    assert user.last_start_source == "direct"
    assert user.first_started_at is not None
    assert user.last_started_at is not None
    assert user.last_started_at >= user.first_started_at


async def test_statistics_counts_total_and_unique_engagement(database) -> None:
    await create_user(database, 1)
    await create_user(database, 2)
    async with database.session_factory.begin() as session:
        await record_engagement(session, telegram_id=1, kind=EngagementKind.RECIPE, target_id=10)
        await record_engagement(session, telegram_id=1, kind=EngagementKind.RECIPE, target_id=10)
        await record_engagement(session, telegram_id=2, kind=EngagementKind.LESSON, target_id=20)
    async with database.session_factory() as session:
        overview = await get_statistics_overview(session)
    assert overview.total_users == 2
    assert overview.phone_verified == 2
    assert overview.recipe_views == 2
    assert overview.recipe_viewers == 1
    assert overview.lesson_views == 1
    assert overview.lesson_viewers == 1
    assert overview.top_recipes == ((10, 2),)
    assert overview.top_lessons == ((20, 1),)
    assert overview.sources == (("campaign-a", 2),)


async def test_csv_and_xlsx_exports_are_safe_and_structured(database) -> None:
    await create_user(database, 42, name="=FORMULA()")
    async with database.session_factory() as session:
        records = await all_user_records(session)

    csv_payload = build_users_csv(records)
    assert csv_payload.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(csv_payload[3:].decode("utf-8"))))
    assert rows[0][0] == "Telegram ID"
    assert rows[1][2] == "'=FORMULA()"
    assert rows[1][5].startswith("'+998")

    xlsx_payload = build_users_xlsx(records)
    workbook = load_workbook(io.BytesIO(xlsx_payload), data_only=False)
    sheet = workbook["Users"]
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:P2"
    assert sheet["A2"].value == "42"
    assert sheet["C2"].value == "=FORMULA()"
    assert sheet["C2"].data_type == "s"
    assert sheet["F2"].number_format == "@"
    assert isinstance(sheet["H2"].value, datetime)
