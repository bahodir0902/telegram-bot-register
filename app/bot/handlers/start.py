from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.types import User as TelegramUser

from app.bot.keyboards.user import contact_keyboard, subscription_keyboard
from app.config import Settings
from app.db.session import AsyncSessionFactory
from app.services.users import set_subscription_prompt, upsert_user

router = Router(name="start")

WELCOME_TEXT = "👋 <b>Welcome!</b>\n\nThanks for starting the bot."
CONTACT_TEXT = "📱 Please share your phone number to continue."
SUBSCRIPTION_TEXT = (
    "📢 <b>One more step.</b>\n\nPlease subscribe to our channel, then check your subscription."
)


async def send_subscription_prompt(
    message: Message,
    telegram_user: TelegramUser,
    settings: Settings,
    session_factory: AsyncSessionFactory,
) -> Message:
    prompt = await message.answer(
        SUBSCRIPTION_TEXT,
        reply_markup=subscription_keyboard(settings.channel_url),
    )
    async with session_factory.begin() as session:
        await set_subscription_prompt(session, telegram_user.id, prompt.message_id)
    return prompt


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def start_private(
    message: Message,
    settings: Settings,
    session_factory: AsyncSessionFactory,
) -> None:
    sender = message.from_user
    if sender is None:
        return

    async with session_factory.begin() as session:
        user = await upsert_user(
            session,
            telegram_id=sender.id,
            username=sender.username,
            first_name=sender.first_name,
            last_name=sender.last_name,
        )

    await message.answer(WELCOME_TEXT)
    if user.phone_verified_at is None:
        await message.answer(CONTACT_TEXT, reply_markup=contact_keyboard())
        return
    await send_subscription_prompt(message, sender, settings, session_factory)


@router.message(CommandStart())
async def start_outside_private(message: Message) -> None:
    await message.answer("Please open a private chat with me and send /start there.")
