from aiogram.fsm.state import State, StatesGroup


class AdminUpload(StatesGroup):
    waiting_for_media = State()


class AdminChannelAdd(StatesGroup):
    waiting_for_id = State()
    waiting_for_url = State()


class AdminChannelEdit(StatesGroup):
    waiting_for_id = State()
    waiting_for_url = State()
