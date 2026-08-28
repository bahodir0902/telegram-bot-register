from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from app.bot.handlers.start import send_subscription_prompt
from app.bot.keyboards.user import contact_keyboard, language_keyboard
from app.db.session import AsyncSessionFactory
from app.i18n import Language, tr, translated_values
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
    language: Language,
    session_factory: AsyncSessionFactory,
) -> None:
    sender = message.from_user
    contact = message.contact
    if sender is None or contact is None:
        return

    if not contact_belongs_to_user(contact.user_id, sender.id):
        await message.answer(
            tr(language, "contact_wrong_owner"),
            reply_markup=contact_keyboard(language),
        )
        return

    try:
        normalized_phone = normalize_phone_number(contact.phone_number)
    except ValueError:
        await message.answer(
            tr(language, "contact_invalid"),
            reply_markup=contact_keyboard(language),
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
        tr(language, "phone_verified"),
        reply_markup=language_keyboard(language),
    )
    await send_subscription_prompt(message, sender, language, session_factory)


@router.message(F.text.in_(translated_values("share_phone")), F.chat.type == ChatType.PRIVATE)
async def typed_contact_button(message: Message, language: Language) -> None:
    await message.answer(
        tr(language, "contact_prompt"),
        reply_markup=contact_keyboard(language),
    )
