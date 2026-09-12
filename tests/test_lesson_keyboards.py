from app.bot.keyboards.admin import (
    lesson_delete_keyboard,
    lesson_detail_keyboard,
    lesson_list_keyboard,
    lesson_video_delete_keyboard,
    lesson_video_detail_keyboard,
    lesson_videos_keyboard,
)
from app.bot.keyboards.user import lessons_keyboard
from app.db.models import VideoLesson, VideoLessonVideo
from app.i18n import Language
from app.services.lessons import LessonPage, LessonVideoPage


def lesson(lesson_id: int = 1) -> VideoLesson:
    return VideoLesson(
        id=lesson_id,
        title_uz="O‘zbekcha",
        title_ru="Русский",
        title_en="English",
        text_uz="UZ",
        text_ru="RU",
        text_en="EN",
        is_active=True,
        sort_order=10,
    )


def video(video_id: int = 1, lesson_id: int = 1) -> VideoLessonVideo:
    return VideoLessonVideo(
        id=video_id,
        lesson_id=lesson_id,
        telegram_file_id="file",
        sort_order=10,
    )


def callbacks(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_user_lesson_button_is_localized() -> None:
    selected = lesson()
    assert (
        lessons_keyboard(LessonPage((selected,), 0, 1, 1), Language.UZ).inline_keyboard[0][0].text
        == "O‘zbekcha"
    )
    assert (
        lessons_keyboard(LessonPage((selected,), 0, 1, 1), Language.RU).inline_keyboard[0][0].text
        == "Русский"
    )
    assert (
        lessons_keyboard(LessonPage((selected,), 0, 1, 1), Language.EN).inline_keyboard[0][0].text
        == "English"
    )


def test_lesson_callbacks_fit_telegram_limit_at_large_ids() -> None:
    large = 2_147_483_647
    page = 999_999
    selected_lesson = lesson(large)
    selected_video = video(large, large)
    lesson_page = LessonPage((selected_lesson,), page, page + 2, large)
    video_page = LessonVideoPage((selected_video,), page, page + 2, large)
    markups = [
        lessons_keyboard(lesson_page, Language.EN),
        lesson_list_keyboard(lesson_page, Language.EN),
        lesson_detail_keyboard(selected_lesson, page, Language.EN),
        lesson_delete_keyboard(selected_lesson, page, Language.EN),
        lesson_videos_keyboard(selected_lesson, video_page, page, Language.EN),
        lesson_video_detail_keyboard(selected_video, page, page, Language.EN),
        lesson_video_delete_keyboard(selected_video, page, page, Language.EN),
    ]
    values = [value for markup in markups for value in callbacks(markup)]
    assert values
    assert max(len(value.encode()) for value in values) <= 64
