from aiogram.fsm.state import State, StatesGroup


class AdminUpload(StatesGroup):
    waiting_for_content = State()
    waiting_for_uz = State()
    waiting_for_ru = State()
    waiting_for_en = State()


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
