from aiogram.fsm.state import State, StatesGroup


class AdminUpload(StatesGroup):
    waiting_for_media = State()
