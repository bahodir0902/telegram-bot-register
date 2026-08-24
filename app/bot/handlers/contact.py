from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message, ReplyKeyboardRemove

from app.bot.handlers.start import CONTACT_TEXT, send_subscription_prompt
from app.bot.keyboards.user import contact_keyboard
from app.config import Settings
from app.db.session import AsyncSessionFactory
from app.services.users import (
    contact_belongs_to_user,
    normalize_phone_number,
    upsert_user,
    verify_phone,
)

router = Router(name="contact")


@router.message(F.contact, F.chat.type == ChatType.PRIVATE)
async def receive_contact(
    message: Message,
    settings: Settings,
    session_factory: AsyncSessionFactory,
) -> None:
    sender = message.from_user
    contact = message.contact
    if sender is None or contact is None:
        return

    if not contact_belongs_to_user(contact.user_id, sender.id):
        await message.answer(
            "That contact does not belong to your Telegram account. "
            "Please use the button to share your own number.",
            reply_markup=contact_keyboard(),
        )
        return

    try:
        normalized_phone = normalize_phone_number(contact.phone_number)
    except ValueError:
        await message.answer(
            "Telegram returned an invalid phone number. Please try sharing it again.",
            reply_markup=contact_keyboard(),
        )
        return

    async with session_factory.begin() as session:
        await upsert_user(
            session,
            telegram_id=sender.id,
            username=sender.username,
            first_name=sender.first_name,
            last_name=sender.last_name,
        )
        await verify_phone(session, sender.id, normalized_phone)

    await message.answer(
        "✅ Phone number verified.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await send_subscription_prompt(message, sender, settings, session_factory)


@router.message(F.text == "📱 Share phone number", F.chat.type == ChatType.PRIVATE)
async def typed_contact_button(message: Message) -> None:
    await message.answer(CONTACT_TEXT, reply_markup=contact_keyboard())
