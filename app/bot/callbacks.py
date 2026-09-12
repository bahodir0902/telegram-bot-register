from aiogram.filters.callback_data import CallbackData


class SubscriptionCallback(CallbackData, prefix="subscription"):
    action: str


class LanguageCallback(CallbackData, prefix="language"):
    code: str


class AdminCallback(CallbackData, prefix="admin"):
    action: str


class UserOptionCallback(CallbackData, prefix="choice"):
    action: str
    option_id: int
    page: int


class UserLessonCallback(CallbackData, prefix="lesson"):
    action: str
    lesson_id: int
    page: int


class AdminOptionCallback(CallbackData, prefix="option"):
    action: str
    option_id: int
    page: int


class OptionItemCallback(CallbackData, prefix="item"):
    action: str
    item_id: int
    option_id: int
    page: int
    option_page: int


class AdminLessonCallback(CallbackData, prefix="adminlesson"):
    action: str
    lesson_id: int
    page: int


class LessonVideoCallback(CallbackData, prefix="lessonvideo"):
    action: str
    video_id: int
    lesson_id: int
    page: int
    lesson_page: int


class StatisticsCallback(CallbackData, prefix="statistics"):
    action: str
    user_id: int
    page: int


class ChannelCallback(CallbackData, prefix="channel"):
    action: str
    channel_id: int
    page: int


class BroadcastCallback(CallbackData, prefix="broadcast"):
    action: str
    broadcast_id: int
