from aiogram.filters.callback_data import CallbackData


class SubscriptionCallback(CallbackData, prefix="subscription"):
    action: str


class LanguageCallback(CallbackData, prefix="language"):
    code: str


class AdminCallback(CallbackData, prefix="admin"):
    action: str


class MediaCallback(CallbackData, prefix="media"):
    action: str
    media_id: int
    page: int


class ChannelCallback(CallbackData, prefix="channel"):
    action: str
    channel_id: int
    page: int
