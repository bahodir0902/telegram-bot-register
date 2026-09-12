from aiogram.fsm.state import State, StatesGroup


class AdminOptionCreate(StatesGroup):
    waiting_for_name_uz = State()
    waiting_for_name_ru = State()
    waiting_for_name_en = State()
    waiting_for_content = State()
    waiting_for_uz = State()
    waiting_for_ru = State()
    waiting_for_en = State()


class AdminOptionNameEdit(StatesGroup):
    waiting_for_value = State()


class AdminOptionItemCompose(StatesGroup):
    waiting_for_content = State()
    waiting_for_uz = State()
    waiting_for_ru = State()
    waiting_for_en = State()


class AdminOptionItemTextEdit(StatesGroup):
    waiting_for_value = State()


class AdminLessonCreate(StatesGroup):
    waiting_for_title_uz = State()
    waiting_for_title_ru = State()
    waiting_for_title_en = State()
    waiting_for_text_uz = State()
    waiting_for_text_ru = State()
    waiting_for_text_en = State()
    waiting_for_videos = State()


class AdminLessonEdit(StatesGroup):
    waiting_for_value = State()


class AdminLessonVideoAdd(StatesGroup):
    waiting_for_videos = State()


class AdminLessonVideoReplace(StatesGroup):
    waiting_for_video = State()


class AdminBroadcast(StatesGroup):
    waiting_for_content = State()
    waiting_for_uz = State()
    waiting_for_ru = State()
    waiting_for_en = State()
    waiting_for_confirmation = State()


class AdminChannelAdd(StatesGroup):
    waiting_for_id = State()
    waiting_for_url = State()


class AdminChannelEdit(StatesGroup):
    waiting_for_id = State()
    waiting_for_url = State()
