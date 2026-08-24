from aiogram.filters.callback_data import CallbackData


class SubscriptionCallback(CallbackData, prefix="subscription"):
    action: str


class AdminCallback(CallbackData, prefix="admin"):
    action: str


class MediaCallback(CallbackData, prefix="media"):
    action: str
    media_id: int
    page: int
